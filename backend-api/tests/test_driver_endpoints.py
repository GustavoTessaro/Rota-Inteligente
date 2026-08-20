from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Endereco, Organizacao, Pedido, Rota, RotaEntrega, StatusRota, Usuario, Perfil


def _login(client: TestClient, email: str, password: str = "123456") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "senha": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f'Bearer {response.json()["token"]}'}


def _seed_possibly_unassigned_driver(client: TestClient, admin_headers: dict, name: str, email: str) -> Usuario:
    with SessionLocal() as db:
        user = db.query(Usuario).filter(Usuario.email == email).first()
        if user is None:
            user = Usuario(
                nome=name,
                email=email,
                senha_hash="hashed",
                perfil=Perfil.MOTORISTA,
                ativo=True,
                organizacao_id=None,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.perfil = Perfil.MOTORISTA
            user.ativo = True
            user.organizacao_id = None
            db.commit()
            db.refresh(user)
        return user


def _create_persisted_driver_route(admin_headers: dict, client: TestClient, driver_id: int, status: StatusRota = StatusRota.PRONTA) -> int:
    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    with SessionLocal() as db:
        route = Rota(
            nome="Rota para confirmação de carga",
            descricao="Teste de persistência da carga",
            organizacao_id=orgs[0]["id"],
            motorista_id=driver_id,
            status=status,
        )
        db.add(route)
        db.commit()
        db.refresh(route)
        return route.id


def test_route_loading_confirmation_is_persisted_and_scoped(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    drivers = [item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"]]
    driver, other_driver = drivers[0], drivers[1]
    route_id = _create_persisted_driver_route(admin_headers, client, driver["id"])
    driver_headers = _login(client, driver["email"])
    other_driver_headers = _login(client, other_driver["email"])

    initial = client.get("/api/rotas/motorista/atual", headers=driver_headers)
    assert initial.status_code == 200
    assert initial.json()["carga_confirmada"] is False

    confirmed = client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["carga_confirmada"] is True

    repeated = client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers)
    assert repeated.status_code == 200
    assert repeated.json()["carga_confirmada"] is True

    reloaded = client.get("/api/rotas/motorista/atual", headers=driver_headers)
    assert reloaded.status_code == 200
    assert reloaded.json()["carga_confirmada"] is True

    forbidden = client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=other_driver_headers)
    assert forbidden.status_code == 403


def test_route_loading_confirmation_rejects_finished_or_cancelled_routes(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])
    route_id = _create_persisted_driver_route(admin_headers, client, driver["id"])

    with SessionLocal() as db:
        route = db.get(Rota, route_id)
        assert route is not None
        route.status = StatusRota.CANCELADA
        db.commit()

    response = client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers)
    assert response.status_code == 422

    with SessionLocal() as db:
        route = db.get(Rota, route_id)
        assert route is not None
        route.status = StatusRota.FINALIZADA
        db.commit()

    response = client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers)
    assert response.status_code == 422


def test_get_motorista_rota_atual_returns_active_route(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])

    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]

    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = next(item for item in deliveries if item["status"] == "AGUARDANDO_COLETA")

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota ativa do motorista",
            "descricao": "Teste de rota do motorista",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "EM_EXECUCAO",
            "pedido_ids": [selected["pedido_id"]],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text

    response = client.get("/api/rotas/motorista/atual", headers=driver_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["motorista_id"] == driver["id"]
    assert data["status"] == "EM_EXECUCAO"
    assert data["route_geometry"] is not None
    assert "entregas" in data
    assert data["progresso_percentual"] >= 0
    assert data["distancia_prevista"] >= 0
    assert data["duracao_prevista"] >= 0
    assert "origem_endereco_id" in data or "origem" in data
    assert data.get("organizacao") is not None
    assert data["organizacao"]["nome"]
    assert data["entregas"][0].get("destino") is not None or data["entregas"][0].get("endereco_destino_formatado")


def test_get_motorista_rota_atual_returns_404_when_no_active_route(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])

    response = client.get("/api/rotas/motorista/atual", headers=driver_headers)
    assert response.status_code == 404, response.text
    assert "Nenhuma rota ativa" in response.json()["detail"]


def test_get_motorista_rota_atual_rejects_non_driver(client: TestClient, admin_headers: dict) -> None:
    response = client.get("/api/rotas/motorista/atual", headers=admin_headers)
    assert response.status_code == 403, response.text
    assert "Apenas motoristas" in response.json()["detail"]


def test_get_sequencia_carregamento_returns_inverted_order(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])
    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]

    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = [item for item in deliveries if item["status"] == "AGUARDANDO_COLETA"][:3]
    assert len(selected) >= 3, "Necessário pelo menos 3 entregas válidas para testar a ordem invertida"

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota com ordem invertida",
            "descricao": "Sequência de carregamento",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [item["pedido_id"] for item in selected],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text
    route_id = route_response.json()["id"]

    response = client.get(f"/api/rotas/{route_id}/sequencia-carregamento", headers=driver_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) == 3
    assert data[0]["ordem_visita"] >= data[1]["ordem_visita"] >= data[2]["ordem_visita"]


def test_get_sequencia_carregamento_rejects_other_driver(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    drivers = [item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"]]
    driver_a, driver_b = drivers[0], drivers[1]

    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = next(item for item in deliveries if item["status"] == "AGUARDANDO_COLETA")

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota de outro motorista",
            "organizacao_id": org["id"],
            "motorista_id": driver_a["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [selected["pedido_id"]],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text
    route_id = route_response.json()["id"]

    other_driver_headers = _login(client, driver_b["email"])
    response = client.get(f"/api/rotas/{route_id}/sequencia-carregamento", headers=other_driver_headers)
    assert response.status_code == 403, response.text
    assert "Acesso negado" in response.json()["detail"]


def test_get_sequencia_carregamento_returns_404_for_missing_route(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])

    response = client.get("/api/rotas/999999/sequencia-carregamento", headers=driver_headers)
    assert response.status_code == 404, response.text


def test_driver_can_start_own_route(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])
    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = next(item for item in deliveries if item["status"] == "AGUARDANDO_COLETA")

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota do motorista pronta",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [selected["pedido_id"]],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text
    route_id = route_response.json()["id"]

    confirm_response = client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers)
    assert confirm_response.status_code == 200, confirm_response.text
    assert confirm_response.json()["carga_confirmada"] is True

    response = client.patch(
        f"/api/rotas/{route_id}/status",
        headers=driver_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Iniciei a rota"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "EM_EXECUCAO"
    assert response.json()["motorista_id"] == driver["id"]


def test_route_start_requires_loading_confirmation(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])

    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = [item for item in deliveries if item["status"] == "AGUARDANDO_COLETA"][:2]
    assert len(selected) >= 2

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota sem carga confirmada",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [item["pedido_id"] for item in selected],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text
    route_id = route_response.json()["id"]

    response = client.patch(
        f"/api/rotas/{route_id}/status",
        headers=driver_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Tentativa de início sem confirmação"},
    )
    assert response.status_code == 422, response.text
    assert "carga_confirmada" in response.json()["detail"].lower()


def test_route_start_confirms_and_marks_pending_deliveries_as_em_rota(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])

    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = [item for item in deliveries if item["status"] == "AGUARDANDO_COLETA"][:2]
    assert len(selected) >= 2

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota com carga confirmada",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [item["pedido_id"] for item in selected],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text
    route_id = route_response.json()["id"]

    confirm_response = client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers)
    assert confirm_response.status_code == 200, confirm_response.text
    assert confirm_response.json()["carga_confirmada"] is True

    response = client.patch(
        f"/api/rotas/{route_id}/status",
        headers=driver_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Viagem iniciada"},
    )
    assert response.status_code == 200, response.text
    route_payload = response.json()
    assert route_payload["status"] == "EM_EXECUCAO"
    assert route_payload["carga_confirmada"] is True
    assert any(item["status"] == "EM_ROTA" for item in route_payload["entregas"])


def test_get_motorista_rota_atual_prefers_em_execucao_over_other_statuses(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])
    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    chosen = [item for item in deliveries if item["status"] == "AGUARDANDO_COLETA"][:2]
    assert len(chosen) >= 2

    first = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota pronta",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [chosen[0]["pedido_id"]],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    second = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota em execução",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "EM_EXECUCAO",
            "pedido_ids": [chosen[1]["pedido_id"]],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert first.status_code == 201 and second.status_code == 201, (first.text, second.text)

    response = client.get("/api/rotas/motorista/atual", headers=driver_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "EM_EXECUCAO"


def test_route_progress_and_finalization_after_last_delivery(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])
    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = [item for item in deliveries if item["status"] == "AGUARDANDO_COLETA"][:2]
    assert len(selected) >= 2

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota com finalização automática",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [item["pedido_id"] for item in selected],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text
    route_id = route_response.json()["id"]

    confirm_response = client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers)
    assert confirm_response.status_code == 200, confirm_response.text

    start_response = client.patch(
        f"/api/rotas/{route_id}/status",
        headers=driver_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Viagem iniciada"},
    )
    assert start_response.status_code == 200, start_response.text
    assert start_response.json()["status"] == "EM_EXECUCAO"

    for delivery in selected:
        assign_response = client.patch(
            f"/api/entregas/{delivery['id']}/atribuir",
            headers=admin_headers,
            json={"entregador_id": driver["id"]},
        )
        assert assign_response.status_code == 200, assign_response.text

    first_delivery = selected[0]
    client.post(
        f"/api/entregas/{first_delivery['id']}/comprovante",
        headers=driver_headers,
        json={
            "nome_recebedor": "Cliente 1",
            "documento_recebedor": "11122233344",
            "observacao": "Entrega concluída",
        },
    )
    first_update = client.patch(
        f"/api/entregas/{first_delivery['id']}/status",
        headers=driver_headers,
        json={"status": "ENTREGUE", "observacao": "Primeira entrega concluída"},
    )
    assert first_update.status_code == 200, first_update.text
    route_after_first = client.get(f"/api/rotas/{route_id}", headers=driver_headers).json()
    assert route_after_first["progresso_percentual"] == 50
    assert route_after_first["status"] == "EM_EXECUCAO"

    second_delivery = selected[1]
    client.post(
        f"/api/entregas/{second_delivery['id']}/comprovante",
        headers=driver_headers,
        json={
            "nome_recebedor": "Cliente 2",
            "documento_recebedor": "22233344455",
            "observacao": "Última entrega concluída",
        },
    )
    second_update = client.patch(
        f"/api/entregas/{second_delivery['id']}/status",
        headers=driver_headers,
        json={"status": "ENTREGUE", "observacao": "Última entrega concluída"},
    )
    assert second_update.status_code == 200, second_update.text

    completed = client.get(f"/api/rotas/{route_id}", headers=driver_headers).json()
    assert completed["status"] == "FINALIZADA"
    assert completed["progresso_percentual"] == 100
    assert completed["data_conclusao"] is not None
    assert any(item["evento"] == "FINALIZADA" for item in completed["historico"])


def test_driver_route_next_delivery_skips_not_delivered_and_is_stable_after_reload(
    client: TestClient, admin_headers: dict
) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])
    org = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = [item for item in deliveries if item["status"] == "AGUARDANDO_COLETA"][:2]
    assert len(selected) >= 2

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota de avanço após não entrega",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [item["pedido_id"] for item in selected],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text
    route_id = route_response.json()["id"]
    assert client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers).status_code == 200
    assert client.patch(
        f"/api/rotas/{route_id}/status",
        headers=driver_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA"},
    ).status_code == 200

    initial = client.get("/api/rotas/motorista/atual", headers=driver_headers).json()
    first_id = initial["entregas"][0]["entrega_id"]
    second_id = initial["entregas"][1]["entrega_id"]
    assert initial["proxima_entrega"]["entrega_id"] == first_id

    for delivery_id in (first_id, second_id):
        assigned = client.patch(
            f"/api/entregas/{delivery_id}/atribuir",
            headers=admin_headers,
            json={"entregador_id": driver["id"]},
        )
        assert assigned.status_code == 200, assigned.text

    update = client.patch(
        f"/api/entregas/{first_id}/status",
        headers=driver_headers,
        json={"status": "NAO_ENTREGUE", "observacao": "Cliente ausente"},
    )
    assert update.status_code == 200, update.text

    advanced = client.get("/api/rotas/motorista/atual", headers=driver_headers).json()
    reloaded = client.get("/api/rotas/motorista/atual", headers=driver_headers).json()
    assert advanced["proxima_entrega"]["entrega_id"] == second_id
    assert advanced["proxima_entrega"]["status"] != "NAO_ENTREGUE"
    assert reloaded["proxima_entrega"]["entrega_id"] == second_id


def test_driver_route_next_delivery_follows_optimized_sequence_through_completion(
    client: TestClient, admin_headers: dict
) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])
    org = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    selected = [item for item in deliveries if item["status"] == "AGUARDANDO_COLETA"][:3]
    assert len(selected) == 3

    route_response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota com sequência otimizada canônica",
            "organizacao_id": org["id"],
            "motorista_id": driver["id"],
            "veiculo_id": None,
            "status": "PRONTA",
            "pedido_ids": [item["pedido_id"] for item in selected],
            "pontos_coleta_ids": [org["id"]],
        },
    )
    assert route_response.status_code == 201, route_response.text
    route_id = route_response.json()["id"]

    with SessionLocal() as db:
        route = db.get(Rota, route_id)
        entries = sorted(route.entregas, key=lambda entry: entry.ordem_visita)
        entries[0].sequencia_otimizada = 2
        entries[1].sequencia_otimizada = 1
        entries[2].sequencia_otimizada = 3
        db.commit()

    assert client.patch(f"/api/rotas/{route_id}/confirmar-carga", headers=driver_headers).status_code == 200
    start = client.patch(
        f"/api/rotas/{route_id}/status",
        headers=driver_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA"},
    )
    assert start.status_code == 200, start.text

    initial = client.get("/api/rotas/motorista/atual", headers=driver_headers).json()
    optimized_entries = sorted(initial["entregas"], key=lambda item: item["sequencia_otimizada"])
    assert initial["proxima_entrega"]["entrega_id"] == optimized_entries[0]["entrega_id"]

    for item in optimized_entries:
        assigned = client.patch(
            f"/api/entregas/{item['entrega_id']}/atribuir",
            headers=admin_headers,
            json={"entregador_id": driver["id"]},
        )
        assert assigned.status_code == 200, assigned.text

    first_id = optimized_entries[0]["entrega_id"]
    receipt = client.post(
        f"/api/entregas/{first_id}/comprovante",
        headers=driver_headers,
        json={"nome_recebedor": "Cliente 1", "documento_recebedor": "111", "observacao": "OK"},
    )
    assert receipt.status_code == 201, receipt.text
    delivered = client.patch(
        f"/api/entregas/{first_id}/status",
        headers=driver_headers,
        json={"status": "ENTREGUE", "observacao": "Entregue"},
    )
    assert delivered.status_code == 200, delivered.text
    after_delivered = client.get("/api/rotas/motorista/atual", headers=driver_headers).json()
    assert after_delivered["proxima_entrega"]["entrega_id"] == optimized_entries[1]["entrega_id"]

    second_id = optimized_entries[1]["entrega_id"]
    not_delivered = client.patch(
        f"/api/entregas/{second_id}/status",
        headers=driver_headers,
        json={"status": "NAO_ENTREGUE", "observacao": "Cliente ausente"},
    )
    assert not_delivered.status_code == 200, not_delivered.text
    after_failed = client.get("/api/rotas/motorista/atual", headers=driver_headers).json()
    assert after_failed["proxima_entrega"]["entrega_id"] == optimized_entries[2]["entrega_id"]
    reloaded = client.get("/api/rotas/motorista/atual", headers=driver_headers).json()
    assert reloaded["proxima_entrega"]["entrega_id"] == optimized_entries[2]["entrega_id"]

    last_id = optimized_entries[2]["entrega_id"]
    receipt = client.post(
        f"/api/entregas/{last_id}/comprovante",
        headers=driver_headers,
        json={"nome_recebedor": "Cliente 3", "documento_recebedor": "333", "observacao": "OK"},
    )
    assert receipt.status_code == 201, receipt.text
    completed_delivery = client.patch(
        f"/api/entregas/{last_id}/status",
        headers=driver_headers,
        json={"status": "ENTREGUE", "observacao": "Entregue"},
    )
    assert completed_delivery.status_code == 200, completed_delivery.text
    completed_route = client.get(f"/api/rotas/{route_id}", headers=driver_headers)
    assert completed_route.status_code == 200, completed_route.text
    assert completed_route.json()["status"] == "FINALIZADA"
    assert completed_route.json()["progresso_percentual"] == 100
