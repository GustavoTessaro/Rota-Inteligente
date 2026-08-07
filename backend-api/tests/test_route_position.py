from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Rota, RotaPosicao


def route_position_payload() -> dict:
    with SessionLocal() as db:
        route = db.get(Rota, 1)
        assert route is not None
        return {
            "latitude": "-23.550520",
            "longitude": "-46.633308",
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat(),
            "velocidade": "55.5",
            "heading": "120.0",
            "accuracy": "5.0",
            "endereco": "Rua Teste, 123",
            "provider": "gps",
            "motorista_id": route.motorista_id,
            "veiculo_id": route.veiculo_id,
        }


def test_create_route_position_persists(client: TestClient, admin_headers: dict) -> None:
    payload = route_position_payload()
    response = client.post('/api/rotas/1/posicoes', headers=admin_headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data['rota_id'] == 1
    assert Decimal(data['latitude']) == Decimal(payload['latitude'])
    assert Decimal(data['longitude']) == Decimal(payload['longitude'])
    assert data['provider'] == 'gps'
    assert data['motorista_id'] == payload['motorista_id']
    assert data['veiculo_id'] == payload['veiculo_id']

    with SessionLocal() as db:
        position = db.get(RotaPosicao, data['id'])
        assert position is not None
        assert position.rota_id == 1
        assert position.latitude == Decimal(payload['latitude'])
        assert position.longitude == Decimal(payload['longitude'])
        assert position.provider == 'gps'


def test_create_route_position_broadcasts(client: TestClient, admin_headers: dict) -> None:
    payload = route_position_payload()

    with client.websocket_connect('/ws/tracking') as websocket:
        response = client.post('/api/rotas/1/posicoes', headers=admin_headers, json=payload)
        assert response.status_code == 201
        data = response.json()

        msg = websocket.receive_json()
        assert msg['type'] == 'rota_posicao'
        assert msg['payload']['id'] == data['id']
        assert msg['payload']['rota_id'] == 1
        assert msg['payload']['provider'] == 'gps'


def test_create_route_position_rejects_invalid_coordinates(client: TestClient, admin_headers: dict) -> None:
    payload = route_position_payload()
    payload['latitude'] = '91.0'

    response = client.post('/api/rotas/1/posicoes', headers=admin_headers, json=payload)

    assert response.status_code == 422


def test_create_route_position_rejects_unknown_vehicle(client: TestClient, admin_headers: dict) -> None:
    payload = route_position_payload()
    payload['veiculo_id'] = 9999

    response = client.post('/api/rotas/1/posicoes', headers=admin_headers, json=payload)

    assert response.status_code == 404


def test_create_route_position_rejects_vehicle_not_matching_route(client: TestClient, admin_headers: dict) -> None:
    payload = route_position_payload()
    payload['veiculo_id'] = 2

    response = client.post('/api/rotas/1/posicoes', headers=admin_headers, json=payload)

    assert response.status_code == 422


def test_create_route_position_integration_persist_and_broadcast(client: TestClient, admin_headers: dict) -> None:
    payload = route_position_payload()

    with client.websocket_connect('/ws/tracking') as websocket:
        response = client.post('/api/rotas/1/posicoes', headers=admin_headers, json=payload)
        assert response.status_code == 201
        created = response.json()

        with SessionLocal() as db:
            persisted = db.get(RotaPosicao, created['id'])
            assert persisted is not None
            assert persisted.rota_id == 1
            assert persisted.veiculo_id == payload['veiculo_id']
            assert persisted.motorista_id == payload['motorista_id']

        msg = websocket.receive_json()
        assert msg['type'] == 'rota_posicao'
        assert msg['payload']['id'] == created['id']
        assert msg['payload']['veiculo_id'] == payload['veiculo_id']
