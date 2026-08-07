from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import RotaPosicao


def route_position_payload() -> dict:
    return {
        "latitude": "-23.550520",
        "longitude": "-46.633308",
        "timestamp": datetime.utcnow().replace(microsecond=0).isoformat(),
        "velocidade": "55.5",
        "heading": "120.0",
        "accuracy": "5.0",
        "endereco": "Rua Teste, 123",
        "provider": "gps",
        "motorista_id": 1,
        "veiculo_id": 1,
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
    assert data['motorista_id'] == 1
    assert data['veiculo_id'] == 1

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
