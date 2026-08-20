from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.deps import ensure_delivery_can_be_routed
from app.models import Cliente, Endereco, Entrega, Organizacao, Pedido, Perfil, Rota, RotaEntrega, StatusEntrega, StatusRota, Usuario


def _login(client, email, password="123456"):
    response = client.post("/api/auth/login", json={"email": email, "senha": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _context():
    with SessionLocal() as db:
        driver = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA).order_by(Usuario.id))
        organization = db.get(Organizacao, driver.organizacao_id)
        address = db.scalar(select(Endereco).order_by(Endereco.id))
        existing_order_ids = select(Entrega.pedido_id)
        order = db.scalar(select(Pedido).where(~Pedido.id.in_(existing_order_ids)).order_by(Pedido.id))
        if order is None:
            customer = db.scalar(select(Cliente).order_by(Cliente.id))
            order = Pedido(
                cliente_id=customer.id,
                organizacao_id=organization.id,
                endereco_entrega_id=address.id,
                numero_pedido="PED-TESTE-ELEGIBILIDADE",
                criado_por=driver.id,
            )
            db.add(order)
            db.flush()
        order.organizacao_id = organization.id
        order.endereco_entrega_id = address.id if address else order.endereco_entrega_id
        db.commit()
        return driver, organization, address, order


def _create_delivery(db, driver, address, order, status):
    delivery = Entrega(
        pedido_id=order.id,
        entregador_id=driver.id,
        endereco_origem_id=address.id,
        endereco_destino_id=address.id,
        status=status,
    )
    db.add(delivery)
    db.flush()
    return delivery


@pytest.mark.parametrize("status", [
    StatusEntrega.COLETADA,
    StatusEntrega.EM_ROTA,
    StatusEntrega.ENTREGUE,
    StatusEntrega.NAO_ENTREGUE,
    StatusEntrega.CANCELADA,
])
def test_new_route_rejects_existing_non_plannable_delivery(client, admin_headers, status):
    driver, organization, address, order = _context()
    with SessionLocal() as db:
        order.status = "ABERTO"
        delivery = _create_delivery(db, driver, address, order, status)
        db.commit()
        delivery_id = delivery.id
        order_id = order.id

    payload = {
        "nome": f"Não aceitar {status.value}",
        "descricao": "Teste",
        "organizacao_id": organization.id,
        "motorista_id": driver.id,
        "veiculo_id": None,
        "status": "PRONTA",
        "pedido_ids": [order_id],
        "pontos_coleta_ids": [organization.id],
    }
    with patch("app.routers.rotas._resolve_address_coordinates", return_value={"latitude": -23.55, "longitude": -46.63}):
        response = client.post("/api/rotas/gerar", headers=admin_headers, json=payload)
    assert response.status_code == 422, response.text
    assert delivery_id not in [item.get("entrega_id") for item in response.json().get("entregas", [])]


def test_new_route_accepts_existing_aguardando_coleta_delivery(client, admin_headers):
    driver, organization, address, order = _context()
    with SessionLocal() as db:
        order.status = "ABERTO"
        delivery = _create_delivery(db, driver, address, order, StatusEntrega.AGUARDANDO_COLETA)
        db.commit()
        delivery_id = delivery.id

    with SessionLocal() as db:
        order = db.get(Pedido, order.id)
        delivery = db.get(Entrega, delivery_id)
        ensure_delivery_can_be_routed(db, order, delivery)


def test_route_with_only_terminal_deliveries_cannot_start(client, admin_headers):
    driver, organization, address, order = _context()
    with SessionLocal() as db:
        route = Rota(
            nome="Rota sem pendências",
            descricao="Teste",
            organizacao_id=organization.id,
            motorista_id=driver.id,
            status=StatusRota.PRONTA,
            carga_confirmada=True,
        )
        db.add(route)
        db.flush()
        delivery = _create_delivery(db, driver, address, order, StatusEntrega.NAO_ENTREGUE)
        db.add(RotaEntrega(rota_id=route.id, entrega_id=delivery.id, ordem_visita=1, sequencia_otimizada=1))
        db.commit()
        route_id = route.id

    response = client.patch(
        f"/api/rotas/{route_id}/status",
        headers=_login(client, driver.email),
        json={"status": "EM_EXECUCAO"},
    )
    assert response.status_code == 422, response.text
    assert "entregas pendentes" in response.json()["detail"].lower()
