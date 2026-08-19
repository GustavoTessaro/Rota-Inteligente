from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Endereco, Entrega, Organizacao, Pedido, Rota, RotaEntrega, StatusEntrega, StatusPedido, StatusRota, Usuario
from app.services.google_maps_service import GoogleMapsService, _encode_polyline


def _generate_single_order_route(client: TestClient, admin_headers: dict, order: dict, status: str = "PRONTA", expected_status: int = 201) -> dict | None:
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    organization = next(item for item in organizations if item.get("endereco_id"))
    with patch("app.routers.rotas.RouteOptimizationService.optimize_route", return_value={
        "optimized_order": [0],
        "ordered_waypoints": [{"lat": -27.811516, "lng": -50.319300}],
        "distance_meters": 1000,
        "duration_seconds": 120,
        "encoded_polyline": "encoded-test",
    }):
        response = client.post(
            "/api/rotas/gerar",
            headers=admin_headers,
            json={
                "nome": "Rota de regressão de ciclo",
                "descricao": "Valida reuso e estados de entrega",
                "organizacao_id": organization["id"],
                "status": status,
                "pedido_ids": [order["id"]],
                "pontos_coleta_ids": [organization["id"]],
            },
        )
    assert response.status_code == expected_status, response.text
    return response.json() if response.status_code == 201 else None


def _fresh_order(client: TestClient, admin_headers: dict) -> dict:
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    organization = next(item for item in organizations if item.get("endereco_id"))
    with SessionLocal() as db:
        admin = db.query(Usuario).filter(Usuario.email == "admin@sistema.com").one()
        source = db.query(Pedido).filter(Pedido.endereco_entrega_id.isnot(None)).first()
        order = Pedido(
            cliente_id=source.cliente_id,
            organizacao_id=organization["id"],
            endereco_entrega_id=source.endereco_entrega_id,
            numero_pedido=f"TDD-{uuid4().hex[:10].upper()}",
            status=StatusPedido.ABERTO,
            criado_por=admin.id,
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return {"id": order.id}


def test_completed_delivery_finalizes_order_and_rejects_new_route(client: TestClient, admin_headers: dict) -> None:
    """The normal flow has one operational delivery per order; history may contain more links."""
    order = _fresh_order(client, admin_headers)
    deliveries_before = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    route = _generate_single_order_route(client, admin_headers, order)
    delivery_id = route["entregas"][0]["entrega_id"]
    client.post(f"/api/entregas/{delivery_id}/comprovante", headers=admin_headers, json={"nome_recebedor": "Recebedor", "documento_recebedor": "123"})
    completed = client.patch(f"/api/entregas/{delivery_id}/status", headers=admin_headers, json={"status": "ENTREGUE", "observacao": "Concluída"})
    assert completed.status_code == 200
    with SessionLocal() as db:
        assert db.get(Pedido, order["id"]).status == StatusPedido.FINALIZADO

    deliveries_after = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    links_before = len(client.get(f"/api/rotas/{route['id']}", headers=admin_headers).json()["entregas"])
    rejected = _generate_single_order_route(client, admin_headers, order, expected_status=422)
    assert rejected is None
    assert len(deliveries_after) == len(deliveries_before) + 1
    assert links_before == 1


def test_cancelled_route_keeps_delivery_reusable_without_active_duplicate(client: TestClient, admin_headers: dict) -> None:
    order = _fresh_order(client, admin_headers)
    route_a = _generate_single_order_route(client, admin_headers, order)
    delivery_id = route_a["entregas"][0]["entrega_id"]
    cancelled = client.patch(f"/api/rotas/{route_a['id']}/status", headers=admin_headers, json={"status": "CANCELADA"})
    assert cancelled.status_code == 200
    route_b = _generate_single_order_route(client, admin_headers, order)
    assert route_b["id"] != route_a["id"]
    with SessionLocal() as db:
        links = db.query(RotaEntrega).filter(RotaEntrega.entrega_id == delivery_id).all()
        routes = {link.rota_id: db.get(Rota, link.rota_id).status for link in links}
        assert routes[route_a["id"]] == StatusRota.CANCELADA
        assert routes[route_b["id"]] in {StatusRota.PRONTA, StatusRota.PLANEJADA}


def test_active_route_rejects_second_route_for_same_order(client: TestClient, admin_headers: dict) -> None:
    order = _fresh_order(client, admin_headers)
    _generate_single_order_route(client, admin_headers, order, status="PRONTA")
    assert _generate_single_order_route(client, admin_headers, order, status="PRONTA", expected_status=422) is None


def test_delivered_delivery_cannot_return_to_operational_status(client: TestClient, admin_headers: dict) -> None:
    order = _fresh_order(client, admin_headers)
    route = _generate_single_order_route(client, admin_headers, order)
    delivery_id = route["entregas"][0]["entrega_id"]
    client.post(f"/api/entregas/{delivery_id}/comprovante", headers=admin_headers, json={"nome_recebedor": "Recebedor", "documento_recebedor": "456"})
    assert client.patch(f"/api/entregas/{delivery_id}/status", headers=admin_headers, json={"status": "ENTREGUE"}).status_code == 200
    for status in ["AGUARDANDO_COLETA", "COLETADA", "EM_ROTA"]:
        response = client.patch(f"/api/entregas/{delivery_id}/status", headers=admin_headers, json={"status": status})
        assert response.status_code == 422


def _decode_polyline(encoded: str) -> list[tuple[float, float]]:
    points = []
    index = 0
    lat = 0
    lng = 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            result = 0
            shift = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lng += deltas[1]
        points.append((lat / 100000, lng / 100000))
    return points


def test_encode_polyline_round_trip_preserves_absolute_coordinates() -> None:
    points = [
        {"lat": -27.811516, "lng": -50.319300},
        {"lat": -27.824925, "lng": -50.347499},
        {"lat": -27.798533, "lng": -50.337620},
    ]

    decoded = _decode_polyline(_encode_polyline(points))

    print("ORIGINAL_FIRST =", (points[0]["lat"], points[0]["lng"]))
    print("DECODED_FIRST =", decoded[0])
    print("ORIGINAL_LAST =", (points[-1]["lat"], points[-1]["lng"]))
    print("DECODED_LAST =", decoded[-1])

    assert len(decoded) == len(points)
    for original, actual in zip(points, decoded):
        assert actual[0] == pytest.approx(original["lat"], abs=1e-5)
        assert actual[1] == pytest.approx(original["lng"], abs=1e-5)


def test_default_route_optimization_emits_real_metrics() -> None:
    optimization = GoogleMapsService().optimize_route(
        origin={"lat": -23.550520, "lng": -46.633308},
        destination={"lat": -23.561000, "lng": -46.640000},
        waypoints=[{"lat": -23.555000, "lng": -46.636000}],
    )

    assert optimization["distance_meters"] is not None
    assert optimization["distance_meters"] > 0
    assert optimization["duration_seconds"] is not None
    assert optimization["duration_seconds"] > 0
    assert optimization["encoded_polyline"] is not None


def test_default_route_optimization_uses_urban_speed_for_duration() -> None:
    optimization = GoogleMapsService().optimize_route(
        origin={"lat": -27.815300, "lng": -50.325000},
        destination={"lat": -27.865000, "lng": -50.330000},
        waypoints=[{"lat": -27.835000, "lng": -50.327500}],
    )

    distance_km = optimization["distance_meters"] / 1000
    duration_hours = optimization["duration_seconds"] / 3600
    expected_duration_hours = distance_km / 35

    assert 4.5 <= distance_km <= 6.5
    assert abs(duration_hours - expected_duration_hours) < 0.05
    assert 8 * 60 <= optimization["duration_seconds"] <= 12 * 60


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
    assert Decimal(str(data["duracao_prevista"])) == Decimal("0.07")
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
