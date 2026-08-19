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
    selected = next(item for item in deliveries if item["status"] != "CANCELADA")

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
    selected = [item for item in deliveries if item["status"] != "CANCELADA"][:3]
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
    selected = next(item for item in deliveries if item["status"] != "CANCELADA")

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
    selected = next(item for item in deliveries if item["status"] != "CANCELADA")

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

    response = client.patch(
        f"/api/rotas/{route_id}/status",
        headers=driver_headers,
        json={"status": "EM_EXECUCAO", "evento": "PARTIDA", "observacao": "Iniciei a rota"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "EM_EXECUCAO"
    assert response.json()["motorista_id"] == driver["id"]


def test_get_motorista_rota_atual_prefers_em_execucao_over_other_statuses(client: TestClient, admin_headers: dict) -> None:
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    driver_headers = _login(client, driver["email"])
    orgs = client.get("/api/organizacoes?limit=50&offset=0", headers=admin_headers).json()
    org = orgs[0]
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    chosen = [item for item in deliveries if item["status"] != "CANCELADA"][:2]
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
