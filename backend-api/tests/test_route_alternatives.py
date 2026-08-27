from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import CriterioAlternativaRota, Rota, RotaAlternativa
from test_route_optimization import _create_route_with_delivery, _fresh_order


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "senha": "123456"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_generation_creates_one_route_with_two_alternatives(client, admin_headers):
    route = _create_route_with_delivery(client, admin_headers)

    assert route["alternativa_escolhida_id"] is None
    assert route["distancia_prevista"] == 0
    assert route["duracao_prevista"] == 0
    assert len(route["alternativas"]) == 2
    assert {item["criterio"] for item in route["alternativas"]} == {"MAIS_RAPIDA", "MAIS_CURTA"}
    assert all(item["rota_id"] == route["id"] for item in route["alternativas"])


def test_admin_can_recommend_and_driver_can_select_idempotently(client, admin_headers):
    route = _create_route_with_delivery(client, admin_headers)
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next(item for item in users if item["id"] == route["motorista_id"])
    driver_headers = _login(client, driver["email"])
    shortest = next(item for item in route["alternativas"] if item["criterio"] == "MAIS_CURTA")
    fastest = next(item for item in route["alternativas"] if item["criterio"] == "MAIS_RAPIDA")

    recommended = client.patch(
        f"/api/rotas/{route['id']}/recomendacao",
        headers=admin_headers,
        json={"criterio": "MAIS_RAPIDA"},
    )
    assert recommended.status_code == 200
    assert recommended.json()["alternativa_recomendada_id"] == fastest["id"]

    selected = client.post(
        f"/api/rotas/{route['id']}/selecionar-alternativa",
        headers=driver_headers,
        json={"alternativa_id": shortest["id"]},
    )
    assert selected.status_code == 200
    data = selected.json()
    assert data["alternativa_escolhida_id"] == shortest["id"]
    assert data["distancia_prevista"] == shortest["distancia_prevista"]
    assert data["duracao_prevista"] == shortest["duracao_prevista"]
    assert all(item["sequencia_otimizada"] is not None for item in data["entregas"])

    repeated = client.post(
        f"/api/rotas/{route['id']}/selecionar-alternativa",
        headers=driver_headers,
        json={"alternativa_id": shortest["id"]},
    )
    assert repeated.status_code == 200

    changed = client.post(
        f"/api/rotas/{route['id']}/selecionar-alternativa",
        headers=driver_headers,
        json={"alternativa_id": fastest["id"]},
    )
    assert changed.status_code == 422


def test_route_cannot_start_without_alternative_selection(client, admin_headers):
    route = _create_route_with_delivery(client, admin_headers)

    response = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=admin_headers,
        json={"status": "EM_EXECUCAO"},
    )

    assert response.status_code == 422
    assert "alternativa" in response.json()["detail"].lower()


def test_selected_alternative_allows_route_to_start_after_load_confirmation(client, admin_headers):
    route = _create_route_with_delivery(client, admin_headers)
    driver = next(item for item in client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json() if item["id"] == route["motorista_id"])
    driver_headers = _login(client, driver["email"])
    alternative = route["alternativas"][0]

    selected = client.post(
        f"/api/rotas/{route['id']}/selecionar-alternativa",
        headers=driver_headers,
        json={"alternativa_id": alternative["id"]},
    )
    assert selected.status_code == 200

    confirmed = client.patch(f"/api/rotas/{route['id']}/confirmar-carga", headers=driver_headers)
    assert confirmed.status_code == 200
    started = client.patch(
        f"/api/rotas/{route['id']}/status",
        headers=driver_headers,
        json={"status": "EM_EXECUCAO"},
    )
    assert started.status_code == 200


def test_equivalence_comparison_is_deterministic():
    from app.routers.rotas import _alternatives_are_equivalent

    first = RotaAlternativa(
        criterio=CriterioAlternativaRota.MAIS_RAPIDA,
        distancia_prevista=1,
        duracao_prevista=2,
        route_geometry="same",
        sequencia_json="[1, 2]",
    )
    second = RotaAlternativa(
        criterio=CriterioAlternativaRota.MAIS_CURTA,
        distancia_prevista=1,
        duracao_prevista=2,
        route_geometry="same",
        sequencia_json="[1, 2]",
    )

    assert _alternatives_are_equivalent([first, second]) is True
    second.route_geometry = "different"
    assert _alternatives_are_equivalent([first, second]) is False
