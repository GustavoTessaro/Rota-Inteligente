from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.security import create_token
from app.models import Organizacao, Perfil, Rota, RotaPosicao, StatusRota, Usuario, Veiculo


def route_position_payload() -> tuple[dict, int]:
    with SessionLocal() as db:
        organization = db.scalar(select(Organizacao).where(Organizacao.endereco_id.is_not(None)).order_by(Organizacao.id))
        driver = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA).order_by(Usuario.id))
        vehicle = db.scalar(select(Veiculo).where(Veiculo.organizacao_id == organization.id).order_by(Veiculo.id))
        route = Rota(
            nome="Rota para posição",
            descricao="Fixture de posição",
            organizacao_id=organization.id,
            motorista_id=driver.id,
            veiculo_id=vehicle.id if vehicle else None,
            status=StatusRota.EM_EXECUCAO,
            carga_confirmada=True,
        )
        db.add(route)
        db.commit()
        db.refresh(route)
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
        }, route.id


def driver_headers(payload: dict) -> dict:
    with SessionLocal() as db:
        driver = db.get(Usuario, payload["motorista_id"])
        return {"Authorization": f"Bearer {create_token(driver)}"}


def test_create_route_position_persists(client: TestClient, admin_headers: dict) -> None:
    payload, route_id = route_position_payload()
    response = client.post(f'/api/rotas/{route_id}/posicoes', headers=driver_headers(payload), json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data['rota_id'] == route_id
    assert Decimal(data['latitude']) == Decimal(payload['latitude'])
    assert Decimal(data['longitude']) == Decimal(payload['longitude'])
    assert data['provider'] == 'gps'
    assert data['motorista_id'] == payload['motorista_id']
    assert data['veiculo_id'] == payload['veiculo_id']

    with SessionLocal() as db:
        position = db.get(RotaPosicao, data['id'])
        assert position is not None
        assert position.rota_id == route_id
        assert position.latitude == Decimal(payload['latitude'])
        assert position.longitude == Decimal(payload['longitude'])
        assert position.provider == 'gps'


def test_create_route_position_broadcasts(client: TestClient, admin_headers: dict) -> None:
    payload, route_id = route_position_payload()

    with client.websocket_connect('/ws/tracking', headers=admin_headers) as websocket:
        response = client.post(f'/api/rotas/{route_id}/posicoes', headers=driver_headers(payload), json=payload)
        assert response.status_code == 201
        data = response.json()

        msg = websocket.receive_json()
        assert msg['type'] == 'rota_posicao'
        assert msg['payload']['id'] == data['id']
        assert msg['payload']['rota_id'] == route_id
        assert msg['payload']['provider'] == 'gps'


def test_route_status_broadcasts_vehicle_status(client: TestClient, admin_headers: dict) -> None:
    payload, route_id = route_position_payload()
    with SessionLocal() as db:
        route = db.get(Rota, route_id)
        db.commit()

    with client.websocket_connect('/ws/tracking', headers=admin_headers) as websocket:
        response = client.patch(
            f'/api/rotas/{route_id}/status',
            headers=admin_headers,
            json={"status": "PAUSADA", "evento": "PAUSA"},
        )
        assert response.status_code == 200
        message = websocket.receive_json()
        assert message == {
            "type": "rota_status",
            "payload": {
                "rota_id": route_id,
                "veiculo_id": payload["veiculo_id"],
                "motorista_id": payload["motorista_id"],
                "status": "PAUSADA",
            },
        }


def test_create_route_position_rejects_invalid_coordinates(client: TestClient, admin_headers: dict) -> None:
    payload, route_id = route_position_payload()
    payload['latitude'] = '91.0'

    response = client.post(f'/api/rotas/{route_id}/posicoes', headers=driver_headers(payload), json=payload)

    assert response.status_code == 422


def test_create_route_position_rejects_unknown_vehicle(client: TestClient, admin_headers: dict) -> None:
    payload, route_id = route_position_payload()
    payload['veiculo_id'] = 9999

    response = client.post(f'/api/rotas/{route_id}/posicoes', headers=driver_headers(payload), json=payload)

    assert response.status_code == 404


def test_create_route_position_rejects_vehicle_not_matching_route(client: TestClient, admin_headers: dict) -> None:
    payload, route_id = route_position_payload()
    payload['veiculo_id'] = 2

    response = client.post(f'/api/rotas/{route_id}/posicoes', headers=driver_headers(payload), json=payload)

    assert response.status_code == 422


def test_create_route_position_integration_persist_and_broadcast(client: TestClient, admin_headers: dict) -> None:
    payload, route_id = route_position_payload()

    with client.websocket_connect('/ws/tracking', headers=admin_headers) as websocket:
        response = client.post(f'/api/rotas/{route_id}/posicoes', headers=driver_headers(payload), json=payload)
        assert response.status_code == 201
        created = response.json()

        with SessionLocal() as db:
            persisted = db.get(RotaPosicao, created['id'])
            assert persisted is not None
            assert persisted.rota_id == route_id
            assert persisted.veiculo_id == payload['veiculo_id']
            assert persisted.motorista_id == payload['motorista_id']

        msg = websocket.receive_json()
        assert msg['type'] == 'rota_posicao'
        assert msg['payload']['id'] == created['id']
        assert msg['payload']['veiculo_id'] == payload['veiculo_id']
