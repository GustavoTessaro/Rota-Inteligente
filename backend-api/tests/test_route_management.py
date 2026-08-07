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
        "/api/rotas",
        headers=admin_headers,
        json={
            "nome": "Rota de Teste Etapa 4",
            "descricao": "Rota para validar ciclo de vida",
            "organizacao_id": organization["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "PLANEJADA",
            "data_planejada": datetime.utcnow().replace(microsecond=0).isoformat(),
            "entregas": [{"entrega_id": delivery["id"], "ordem_visita": 1}],
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
        "/api/rotas",
        headers=admin_headers,
        json={
            "nome": "Rota para pausa",
            "descricao": "Validar pausa e retomada",
            "organizacao_id": organizations[0]["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "PLANEJADA",
            "entregas": [{"entrega_id": deliveries[0]["id"], "ordem_visita": 1}],
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
        "/api/rotas",
        headers=admin_headers,
        json={
            "nome": "Rota sem veículo e motorista",
            "descricao": "Rota para validar início",
            "organizacao_id": organization["id"],
            "status": "PLANEJADA",
            "entregas": [{"entrega_id": delivery["id"], "ordem_visita": 1}],
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


def test_gestor_cannot_assign_route_to_other_organization(client: TestClient, admin_headers: dict) -> None:
    gestor_headers = _login(client, "gestor1@sistema.com")
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    other_org = next(item for item in organizations if item["id"] != 1)
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=gestor_headers).json()
    delivery = next(item for item in deliveries if item["status"] != "CANCELADA")

    response = client.post(
        "/api/rotas",
        headers=gestor_headers,
        json={
            "nome": "Rota indevida",
            "descricao": "Gestor não pode criar para outra organização",
            "organizacao_id": other_org["id"],
            "status": "PLANEJADA",
            "entregas": [{"entrega_id": delivery["id"], "ordem_visita": 1}],
        },
    )
    assert response.status_code == 403
