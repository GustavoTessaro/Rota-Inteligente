from datetime import datetime

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Rota, RotaPosicao


def _login(client: TestClient, email: str, password: str = "123456") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "senha": password})
    assert response.status_code == 200
    return {"Authorization": f'Bearer {response.json()["token"]}'}


def test_route_lifecycle_and_tracking_integration(client: TestClient, admin_headers: dict) -> None:
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    users = client.get("/api/usuarios", headers=admin_headers).json()
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()

    vehicle = next(item for item in vehicles if item["ativo"])
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    organization = next(item for item in organizations if item["id"] == vehicle["organizacao_id"])
    delivery = next(item for item in deliveries if item["status"] != "CANCELADA")

    create_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota de Teste Etapa 4",
            "descricao": "Rota para validar ciclo de vida",
            "organizacao_id": organization["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "PLANEJADA",
            "data_planejada": datetime.utcnow().replace(microsecond=0).isoformat(),
            "pedido_ids": [delivery["pedido_id"]],
            "pontos_coleta_ids": [organization["id"]],
        },
    )
    assert create_response.status_code == 201
    route = create_response.json()
    assert route["veiculo_id"] == vehicle["id"]
    assert route["motorista_id"] == driver["id"]
    assert route["entregas"][0]["entrega_id"] == delivery["id"]

    list_response = client.get("/api/rotas?limit=10&offset=0", headers=admin_headers)
    assert list_response.status_code == 200
    assert any(item["id"] == route["id"] for item in list_response.json())

    start_response = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Iniciando"},
    )
    assert start_response.status_code == 200
    started = start_response.json()
    assert started["status"] == "EM_EXECUCAO"
    assert started["data_inicio"] is not None

    with client.websocket_connect("/ws/tracking") as websocket:
        position_response = client.post(
            f"/api/rotas/{route['id']}/posicoes",
            headers=admin_headers,
            json={
                "latitude": -23.55052,
                "longitude": -46.633308,
                "timestamp": datetime.utcnow().replace(microsecond=0).isoformat(),
                "velocidade": 45.5,
                "provider": "gps",
                "veiculo_id": vehicle["id"],
                "motorista_id": driver["id"],
            },
        )
        assert position_response.status_code == 201
        msg = websocket.receive_json()
        assert msg["type"] == "rota_posicao"
        assert msg["payload"]["rota_id"] == route["id"]

    with SessionLocal() as db:
        persisted = db.scalar(
            db.query(RotaPosicao).filter(RotaPosicao.rota_id == route["id"]).order_by(RotaPosicao.id.desc())
        )
        assert persisted is not None
        assert persisted.veiculo_id == vehicle["id"]

    finish_response = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "FINALIZADA", "evento": "FINALIZADA", "observacao": "Concluída"},
    )
    assert finish_response.status_code == 200
    finished = finish_response.json()
    assert finished["status"] == "FINALIZADA"
    assert finished["data_conclusao"] is not None

    cancel_response = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "CANCELADA", "evento": "FINALIZADA", "observacao": "Cancelada após conclusão"},
    )
    assert cancel_response.status_code == 422


def test_route_can_be_paused_and_resumed_with_progress(client: TestClient, admin_headers: dict) -> None:
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    users = client.get("/api/usuarios", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()

    vehicle = next(item for item in vehicles if item["ativo"])
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])

    create_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota para pausa",
            "descricao": "Validar pausa e retomada",
            "organizacao_id": organizations[0]["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "PLANEJADA",
            "pedido_ids": [deliveries[0]["pedido_id"]],
            "pontos_coleta_ids": [organizations[0]["id"]],
        },
    )
    assert create_response.status_code == 201
    route = create_response.json()

    start_response = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Iniciando"},
    )
    assert start_response.status_code == 200

    paused_response = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "PAUSADA", "observacao": "Pausando por manutenção"},
    )
    assert paused_response.status_code == 200
    assert paused_response.json()["status"] == "PAUSADA"

    resumed_response = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "EM_EXECUCAO", "progresso_percentual": 45, "observacao": "Retomando"},
    )
    assert resumed_response.status_code == 200
    assert resumed_response.json()["status"] == "EM_EXECUCAO"
    assert resumed_response.json()["progresso_percentual"] == 45

    history = client.get(f'/api/rotas/{route["id"]}/historico', headers=admin_headers).json()
    assert [item["evento"] for item in history][-2:] == ["PAUSA", "RETOMADA"]


def test_route_start_requires_vehicle_and_driver(client: TestClient, admin_headers: dict) -> None:
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()

    organization = organizations[0]
    delivery = next(item for item in deliveries if item["status"] != "CANCELADA")

    create_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota sem veículo e motorista",
            "descricao": "Rota para validar início",
            "organizacao_id": organization["id"],
            "status": "PLANEJADA",
            "pedido_ids": [delivery["pedido_id"]],
            "pontos_coleta_ids": [organization["id"]],
        },
    )
    assert create_response.status_code == 201
    route = create_response.json()

    start_response = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Iniciando"},
    )
    assert start_response.status_code == 422


def test_driver_only_sees_assigned_route(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios", headers=admin_headers).json()
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()

    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    vehicle = next(item for item in vehicles if item["ativo"])
    organization = next(item for item in organizations if item["id"] == vehicle["organizacao_id"])
    delivery = next(item for item in deliveries if item["status"] != "CANCELADA")

    create_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota do Motorista",
            "descricao": "Rota atribuída a motorista para teste",
            "organizacao_id": organization["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "PLANEJADA",
            "pedido_ids": [delivery["pedido_id"]],
            "pontos_coleta_ids": [organization["id"]],
        },
    )
    assert create_response.status_code == 201

    driver_headers = _login(client, driver["email"])
    routes = client.get("/api/rotas?limit=50&offset=0", headers=driver_headers).json()
    assert routes
    assert all(item["motorista_id"] == driver["id"] for item in routes)


def test_route_execution_uses_optimized_order_for_next_stop(client: TestClient, admin_headers: dict) -> None:
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    users = client.get("/api/usuarios", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()

    vehicle = next(item for item in vehicles if item["ativo"])
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    valid_deliveries = [item for item in deliveries if item["status"] != "CANCELADA"][:2]
    assert len(valid_deliveries) >= 2

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota executada em ordem",
            "descricao": "Teste da ordem da execução",
            "organizacao_id": organizations[0]["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "PRONTA",
            "pedido_ids": [valid_deliveries[0]["pedido_id"], valid_deliveries[1]["pedido_id"]],
            "pontos_coleta_ids": [organizations[0]["id"]],
        },
    )
    assert route_response.status_code == 201
    route = route_response.json()

    ordered = sorted(route["entregas"], key=lambda item: item["ordem_visita"])
    assert [item["entrega_id"] for item in ordered] == [valid_deliveries[0]["id"], valid_deliveries[1]["id"]]

    next_delivery_id = ordered[0]["entrega_id"]
    route_snapshot = client.get(f"/api/rotas/{route['id']}", headers=admin_headers).json()
    route_order = sorted(route_snapshot["entregas"], key=lambda item: item["ordem_visita"])
    assert route_order[0]["entrega_id"] == next_delivery_id
    assert route_order[0]["entrega_id"] in {item["id"] for item in valid_deliveries}


def test_driver_can_complete_current_delivery_and_advance_progress(client: TestClient, admin_headers: dict) -> None:
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    users = client.get("/api/usuarios", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()

    vehicle = next(item for item in vehicles if item["ativo"])
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    valid_deliveries = [item for item in deliveries if item["status"] != "CANCELADA"][:2]

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota de conclusão",
            "descricao": "Validar avanço de progresso",
            "organizacao_id": organizations[0]["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "EM_EXECUCAO",
            "progresso_percentual": 0,
            "pedido_ids": [valid_deliveries[0]["pedido_id"], valid_deliveries[1]["pedido_id"]],
            "pontos_coleta_ids": [organizations[0]["id"]],
        },
    )
    assert route_response.status_code == 201
    route = route_response.json()

    route_start = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Iniciando a rota"},
    )
    assert route_start.status_code == 200

    first_delivery = valid_deliveries[0]
    client.post(
        f"/api/entregas/{first_delivery['id']}/comprovante",
        headers=admin_headers,
        json={
            "nome_recebedor": "Cliente 1",
            "documento_recebedor": "11122233344",
            "observacao": "Concluído na rota",
        },
    )
    delivered = client.patch(
        f"/api/entregas/{first_delivery['id']}/status",
        headers=admin_headers,
        json={"status": "ENTREGUE", "observacao": "Entrega concluída"},
    )
    assert delivered.status_code == 200
    assert delivered.json()["status"] == "ENTREGUE"

    progress = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "EM_EXECUCAO", "progresso_percentual": 50, "observacao": "Avançou para a próxima entrega"},
    )
    assert progress.status_code == 200
    assert progress.json()["progresso_percentual"] == 50

    next_pending = client.get(f"/api/rotas/{route['id']}", headers=admin_headers).json()
    assert next_pending["entregas"][1]["entrega_id"] == valid_deliveries[1]["id"]


def test_route_finalizes_after_all_deliveries_complete(client: TestClient, admin_headers: dict) -> None:
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    users = client.get("/api/usuarios", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()

    vehicle = next(item for item in vehicles if item["ativo"])
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    valid_deliveries = [item for item in deliveries if item["status"] != "CANCELADA"][:1]

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota finalizada",
            "descricao": "Validar finalização da rota",
            "organizacao_id": organizations[0]["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "EM_EXECUCAO",
            "progresso_percentual": 95,
            "pedido_ids": [valid_deliveries[0]["pedido_id"]],
            "pontos_coleta_ids": [organizations[0]["id"]],
        },
    )
    assert route_response.status_code == 201
    route = route_response.json()

    client.post(
        f"/api/entregas/{valid_deliveries[0]['id']}/comprovante",
        headers=admin_headers,
        json={"nome_recebedor": "Cliente final", "documento_recebedor": "33344455566", "observacao": "Conclusão final"},
    )
    client.patch(
        f"/api/entregas/{valid_deliveries[0]['id']}/status",
        headers=admin_headers,
        json={"status": "ENTREGUE", "observacao": "Última entrega concluída"},
    )

    completed = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "FINALIZADA", "progresso_percentual": 100, "evento": "FINALIZADA", "observacao": "Rota concluída"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "FINALIZADA"
    assert completed.json()["progresso_percentual"] == 100


def test_current_backend_does_not_enforce_sequential_delivery_guard(client: TestClient, admin_headers: dict) -> None:
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    users = client.get("/api/usuarios", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()

    vehicle = next(item for item in vehicles if item["ativo"])
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    valid_deliveries = [item for item in deliveries if item["status"] != "CANCELADA"][:2]

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota sem trava sequencial",
            "descricao": "Confirma que a regra não existe no backend atual",
            "organizacao_id": organizations[0]["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "EM_EXECUCAO",
            "pedido_ids": [valid_deliveries[0]["pedido_id"], valid_deliveries[1]["pedido_id"]],
            "pontos_coleta_ids": [organizations[0]["id"]],
        },
    )
    assert route_response.status_code == 201

    client.post(
        f"/api/entregas/{valid_deliveries[1]['id']}/comprovante",
        headers=admin_headers,
        json={"nome_recebedor": "Cliente fora de ordem", "documento_recebedor": "44455566677", "observacao": "Concluído antes do primeiro"},
    )
    status_response = client.patch(
        f"/api/entregas/{valid_deliveries[1]['id']}/status",
        headers=admin_headers,
        json={"status": "ENTREGUE", "observacao": "Conclusão fora da ordem"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "ENTREGUE"


def test_gestor_cannot_assign_route_to_other_organization(client: TestClient, admin_headers: dict) -> None:
    gestor_headers = _login(client, "gestor1@sistema.com")
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    other_org = next(item for item in organizations if item["id"] != 1)
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=gestor_headers).json()
    delivery = next(item for item in deliveries if item["status"] != "CANCELADA")

    response = client.post(
        "/api/rotas/gerar",
        headers=gestor_headers,
        json={
            "nome": "Rota indevida",
            "descricao": "Gestor não pode criar para outra organização",
            "organizacao_id": other_org["id"],
            "status": "PLANEJADA",
            "pedido_ids": [delivery["pedido_id"]],
            "pontos_coleta_ids": [other_org["id"]],
        },
    )
    assert response.status_code == 403
