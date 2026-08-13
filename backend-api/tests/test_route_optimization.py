from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Endereco, Entrega, Rota, RotaEntrega, StatusEntrega


def _create_route_with_delivery(client: TestClient, admin_headers: dict) -> dict:
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    users = client.get("/api/usuarios", headers=admin_headers).json()

    vehicle = next(item for item in vehicles if item["ativo"])
    driver = next(item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"])
    organization = next(item for item in organizations if item["id"] == vehicle["organizacao_id"])
    delivery = next(item for item in deliveries if item["status"] != "CANCELADA")

    with SessionLocal() as db:
        address = db.get(Endereco, delivery["endereco_destino_id"])
        if address is not None:
            address.latitude = Decimal("-23.550520")
            address.longitude = Decimal("-46.633308")
            db.commit()

    response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota otimizada",
            "descricao": "Rota para otimização",
            "organizacao_id": organization["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": driver["id"],
            "status": "PLANEJADA",
            "pedido_ids": [delivery["pedido_id"]],
            "pontos_coleta_ids": [organization["id"]],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_generate_route_optimizes_and_persists_metrics(client: TestClient, admin_headers: dict) -> None:
    route = _create_route_with_delivery(client, admin_headers)

    with patch("app.routers.rotas.RouteOptimizationService.optimize_route", return_value={
        "optimized_order": [0],
        "ordered_waypoints": [{"lat": -23.550520, "lng": -46.633308, "label": "Parada 1"}],
        "distance_meters": 1200,
        "duration_seconds": 240,
        "encoded_polyline": "abc123",
        "google_route_id": "route-123",
        "google_optimization_request_id": "opt-123",
    }):
        response = client.post(
            "/api/rotas/gerar",
            headers=admin_headers,
            json={
                "nome": "Rota gerada e otimizada",
                "descricao": "Deve otimizar ao gerar",
                "organizacao_id": route["organizacao_id"],
                "veiculo_id": route["veiculo_id"],
                "motorista_id": route["motorista_id"],
                "status": "OTIMIZANDO",
                "pedido_ids": [route["entregas"][0]["entrega_id"] if "entrega_id" in route["entregas"][0] else route["entregas"][0]["id"]],
                "pontos_coleta_ids": [route["organizacao_id"]],
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PRONTA"
    assert Decimal(str(data["distancia_prevista"])) == Decimal("1.20")
    assert Decimal(str(data["duracao_prevista"])) == Decimal("4.00")
    assert data["route_geometry"] == "abc123"


def test_optimize_route_requires_existing_route(client: TestClient, admin_headers: dict) -> None:
    response = client.post("/api/rotas/99999/otimizar", headers=admin_headers)
    assert response.status_code == 404


def test_optimize_route_requires_deliveries(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        route = Rota(
            nome="Rota sem entregas",
            descricao="Deve falhar",
            organizacao_id=1,
            status="PLANEJADA",
        )
        db.add(route)
        db.commit()
        db.refresh(route)
        route_id = route.id

    optimize = client.post(f"/api/rotas/{route_id}/otimizar", headers=admin_headers)
    assert optimize.status_code == 422


def test_optimize_route_persists_result_and_sequence(client: TestClient, admin_headers: dict) -> None:
    route = _create_route_with_delivery(client, admin_headers)

    with patch("app.routers.rotas.RouteOptimizationService.optimize_route", return_value={
        "optimized_order": [0],
        "ordered_waypoints": [{"lat": -23.550520, "lng": -46.633308, "label": "Parada 1"}],
        "distance_meters": 1200,
        "duration_seconds": 240,
        "encoded_polyline": "abc123",
        "google_route_id": "route-123",
        "google_optimization_request_id": "opt-123",
    }):
        response = client.post(f"/api/rotas/{route['id']}/otimizar", headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["optimized_order"] == [0]
    assert data["distance_meters"] == 1200
    assert data["encoded_polyline"] == "abc123"

    with SessionLocal() as db:
        persisted = db.get(Rota, route["id"])
        assert persisted is not None
        assert persisted.google_route_id == "route-123"
        assert persisted.google_optimization_request_id == "opt-123"
        assert persisted.route_geometry == "abc123"


def test_optimize_route_rejects_finalized_route(client: TestClient, admin_headers: dict) -> None:
    route = _create_route_with_delivery(client, admin_headers)

    with SessionLocal() as db:
        persisted = db.get(Rota, route["id"])
        assert persisted is not None
        persisted.status = "FINALIZADA"
        db.commit()

    response = client.post(f"/api/rotas/{route['id']}/otimizar", headers=admin_headers)
    assert response.status_code == 422


def test_optimize_route_geocodes_missing_coordinates(client: TestClient, admin_headers: dict) -> None:
    route = _create_route_with_delivery(client, admin_headers)

    with SessionLocal() as db:
        persisted = db.get(Rota, route["id"])
        assert persisted is not None
        entry = persisted.entregas[0]
        delivery = db.get(Entrega, entry.entrega_id)
        if delivery is not None and delivery.endereco_destino_id is not None:
            address = db.get(Endereco, delivery.endereco_destino_id)
            if address is not None:
                address.latitude = None
                address.longitude = None
                db.commit()

    fake_service = type(
        "FakeService",
        (),
        {"geocode": lambda self, query: {"results": [{"geometry": {"location": {"lat": -23.550520, "lng": -46.633308}}}]}}
    )

    with patch("app.routers.rotas.get_geocoding_service", return_value=fake_service()) as geocode_mock, patch("app.routers.rotas.RouteOptimizationService.optimize_route", return_value={
        "optimized_order": [0],
        "ordered_waypoints": [{"lat": -23.550520, "lng": -46.633308, "label": "Parada 1"}],
        "distance_meters": 1000,
        "duration_seconds": 120,
        "encoded_polyline": "abc123",
    }) as optimize_mock:
        response = client.post(f"/api/rotas/{route['id']}/otimizar", headers=admin_headers)

    assert response.status_code == 200
    geocode_mock.assert_called()
    optimize_mock.assert_called_once()
    origin, destination, waypoints = optimize_mock.call_args.args[:3]
    assert origin is not None
    assert destination is not None
    assert waypoints


def test_optimize_route_requires_coordinates(client: TestClient, admin_headers: dict) -> None:
    orders = client.get("/api/pedidos?limit=100&offset=0", headers=admin_headers).json()
    order = next(item for item in orders if item.get("endereco_entrega_id") is not None)
    response = client.post(
        "/api/rotas/gerar",
        headers=admin_headers,
        json={
            "nome": "Rota sem coordenadas",
            "descricao": "Deve falhar",
            "organizacao_id": 1,
            "status": "PLANEJADA",
            "pedido_ids": [order["id"]],
            "pontos_coleta_ids": [1],
        },
    )
    assert response.status_code == 422
    assert "coordenada" in response.json()["detail"].lower()
