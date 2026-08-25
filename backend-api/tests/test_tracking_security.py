import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Endereco, Entrega, Organizacao, Perfil, Pedido, Rota, RotaEntrega, StatusEntrega, StatusRota, Usuario, Veiculo
from app.security import create_token
from app.tracking import manager


@pytest.fixture(autouse=True)
def clear_manager():
    manager.active_connections.clear()
    yield
    manager.active_connections.clear()


def _user(email):
    with SessionLocal() as db:
        return db.scalar(select(Usuario).where(Usuario.email == email))


def _headers(user):
    with SessionLocal() as db:
        persisted = db.get(Usuario, user.id)
        return {"Authorization": f"Bearer {create_token(persisted)}"}


def _route_for(driver, status=StatusRota.EM_EXECUCAO, with_vehicle=True):
    with SessionLocal() as db:
        driver = db.get(Usuario, driver.id)
        organization = db.get(Organizacao, driver.organizacao_id)
        address = db.get(Endereco, organization.endereco_id)
        order = db.scalar(select(Pedido).where(Pedido.organizacao_id == organization.id).order_by(Pedido.id))
        if order is None:
            order = db.scalar(select(Pedido).order_by(Pedido.id))
            if order is not None:
                order.organizacao_id = organization.id
        if address is None or order is None:
            pytest.skip("fixture de organização sem endereço/pedido")
        vehicle = db.scalar(select(Veiculo).where(Veiculo.organizacao_id == organization.id).order_by(Veiculo.id)) if with_vehicle else None
        delivery = Entrega(
            pedido_id=order.id,
            entregador_id=driver.id,
            endereco_origem_id=address.id,
            endereco_destino_id=address.id,
            status=StatusEntrega.AGUARDANDO_COLETA,
        )
        route = Rota(
            nome="Rota tracking segura",
            descricao="Teste",
            organizacao_id=organization.id,
            motorista_id=driver.id,
            veiculo_id=vehicle.id if vehicle else None,
            status=status,
            carga_confirmada=True,
        )
        db.add_all([delivery, route])
        db.flush()
        db.add(RotaEntrega(rota_id=route.id, entrega_id=delivery.id, ordem_visita=1, sequencia_otimizada=1))
        db.commit()
        return route.id, delivery.id, vehicle.id if vehicle else None


def _position(route_id, driver_id, vehicle_id, **changes):
    payload = {
        "latitude": -27.81,
        "longitude": -50.32,
        "timestamp": datetime.now().isoformat(),
        "motorista_id": driver_id,
        "veiculo_id": vehicle_id,
        "provider": "test",
    }
    payload.update(changes)
    return payload


def test_websocket_without_authorization_is_rejected():
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/tracking"):
                pass


def test_websocket_invalid_token_is_rejected():
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/tracking", headers={"Authorization": "Bearer invalid"}):
                pass


def test_motorista_websocket_is_rejected():
    driver = _user("motorista1@sistema.com")
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/tracking", headers=_headers(driver)):
                pass


def test_admin_websocket_is_allowed():
    admin = _user("admin@sistema.com")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/tracking", headers=_headers(admin)) as websocket:
            assert websocket is not None


def test_manager_broadcast_is_scoped_by_organization():
    class Socket:
        def __init__(self):
            self.sent = 0

        async def send_json(self, message):
            self.sent += 1

    manager_a = type("Connection", (), {"websocket": Socket(), "perfil": Perfil.GESTOR, "organizacao_id": 1})()
    manager_b = type("Connection", (), {"websocket": Socket(), "perfil": Perfil.GESTOR, "organizacao_id": 2})()
    manager.active_connections.extend([manager_a, manager_b])
    asyncio.run(manager.broadcast({"type": "rota_posicao", "payload": {}}, organization_id=1))
    assert manager_a.websocket.sent == 1
    assert getattr(manager_b.websocket, "sent", 0) == 0


@pytest.mark.parametrize("status", [StatusRota.PRONTA, StatusRota.PAUSADA, StatusRota.FINALIZADA, StatusRota.CANCELADA])
def test_driver_cannot_publish_position_outside_execution(client: TestClient, status):
    driver = _user("motorista1@sistema.com")
    route_id, _, vehicle_id = _route_for(driver, status=status)
    response = client.post(f"/api/rotas/{route_id}/posicoes", headers=_headers(driver), json=_position(route_id, driver.id, vehicle_id))
    assert response.status_code == 422


def test_driver_can_publish_only_on_own_execution_route(client: TestClient):
    driver = _user("motorista1@sistema.com")
    route_id, _, vehicle_id = _route_for(driver)
    response = client.post(f"/api/rotas/{route_id}/posicoes", headers=_headers(driver), json=_position(route_id, driver.id, vehicle_id))
    assert response.status_code == 201


def test_driver_cannot_publish_with_forged_identity_or_vehicle(client: TestClient):
    driver = _user("motorista1@sistema.com")
    other = _user("motorista2@sistema.com")
    route_id, _, vehicle_id = _route_for(driver)
    response = client.post(f"/api/rotas/{route_id}/posicoes", headers=_headers(driver), json=_position(route_id, driver.id, vehicle_id, motorista_id=other.id))
    assert response.status_code in {403, 422}
    response = client.post(f"/api/rotas/{route_id}/posicoes", headers=_headers(driver), json=_position(route_id, driver.id, vehicle_id, veiculo_id=999999))
    assert response.status_code in {403, 404, 422}


def test_manager_and_admin_cannot_publish_position(client: TestClient):
    driver = _user("motorista1@sistema.com")
    route_id, _, vehicle_id = _route_for(driver)
    for email in ("gestor1@sistema.com", "admin@sistema.com"):
        response = client.post(f"/api/rotas/{route_id}/posicoes", headers=_headers(_user(email)), json=_position(route_id, driver.id, vehicle_id))
        assert response.status_code == 403
