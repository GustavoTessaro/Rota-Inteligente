from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Cliente,
    Endereco,
    Entrega,
    HistoricoEntrega,
    Organizacao,
    Pedido,
    PedidoItem,
    Perfil,
    Produto,
    Rota,
    RotaEntrega,
    StatusEntrega,
    StatusPedido,
    StatusRota,
    Usuario,
)


def _login(client, email):
    response = client.post("/api/auth/login", json={"email": email, "senha": "123456"})
    assert response.status_code == 200, response.text
    return {"Authorization": f'Bearer {response.json()["token"]}'}


def _create_route(client, *, delivery_status=StatusEntrega.EM_ROTA, driver_index=1):
    with SessionLocal() as db:
        admin = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.ADMIN))
        driver = db.scalar(select(Usuario).where(Usuario.email == f"motorista{driver_index}@sistema.com"))
        other_driver = db.scalar(select(Usuario).where(Usuario.email == f"motorista{3 if driver_index != 3 else 2}@sistema.com"))
        organization = db.scalar(select(Organizacao).order_by(Organizacao.id))
        product = db.scalar(select(Produto).where(Produto.ativo.is_(True)).order_by(Produto.id))
        client_record = Cliente(nome=f"Conclusão {driver_index} {delivery_status.value}", ativo=True)
        db.add(client_record)
        db.flush()
        address = Endereco(
            cliente_id=client_record.id,
            logradouro="Rua Teste Conclusão",
            numero="10",
            bairro="Centro",
            cidade="Lages",
            estado="SC",
            cep="88500000",
            tipo="DESTINO",
            latitude=Decimal("-27.815"),
            longitude=Decimal("-50.325"),
        )
        origin = Endereco(
            organizacao_id=organization.id,
            logradouro="Rua Origem Conclusão",
            numero="1",
            bairro="Centro",
            cidade="Lages",
            estado="SC",
            cep="88500000",
            tipo="ORIGEM",
            latitude=Decimal("-27.815"),
            longitude=Decimal("-50.325"),
        )
        db.add_all([address, origin])
        db.flush()
        order = Pedido(
            cliente_id=client_record.id,
            organizacao_id=organization.id,
            endereco_entrega_id=address.id,
            numero_pedido=f"PED-CONCLUSAO-{driver_index}-{delivery_status.value}",
            status=StatusPedido.ABERTO,
            criado_por=admin.id,
            valor_total=Decimal("10"),
        )
        order.itens = [PedidoItem(produto_id=product.id, quantidade=1, valor_unitario=Decimal("10"))]
        db.add(order)
        db.flush()
        delivery = Entrega(
            pedido_id=order.id,
            entregador_id=driver.id,
            endereco_origem_id=origin.id,
            endereco_destino_id=address.id,
            status=delivery_status,
            previsao_entrega=datetime.now(),
        )
        db.add(delivery)
        db.flush()
        route = Rota(
            nome=f"Rota conclusão {driver_index} {delivery_status.value}",
            organizacao_id=organization.id,
            motorista_id=driver.id,
            status=StatusRota.EM_EXECUCAO,
            carga_confirmada=True,
            origem_endereco_id=origin.id,
            progresso_percentual=0,
        )
        route.entregas = [RotaEntrega(entrega_id=delivery.id, ordem_visita=1, sequencia_otimizada=1)]
        db.add(route)
        db.commit()
        return {
            "route_id": route.id,
            "delivery_id": delivery.id,
            "order_id": order.id,
            "driver_headers": _login(client, driver.email),
            "other_headers": _login(client, other_driver.email),
        }


def test_atomic_completion_creates_receipt_and_updates_delivery_order_and_route(client):
    data = _create_route(client)

    response = client.post(
        f"/api/entregas/{data['delivery_id']}/concluir",
        headers=data["driver_headers"],
        json={"nome_recebedor": "Maria", "observacao": "Recebido"},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        delivery = db.get(Entrega, data["delivery_id"])
        order = db.get(Pedido, data["order_id"])
        route = db.get(Rota, data["route_id"])
        assert delivery.status == StatusEntrega.ENTREGUE
        assert delivery.data_entrega is not None
        assert delivery.comprovante.nome_recebedor == "Maria"
        assert delivery.comprovante.documento_recebedor is None
        assert order.status == StatusPedido.FINALIZADO
        assert route.status == StatusRota.FINALIZADA
        assert route.progresso_percentual == 100
        assert db.scalar(select(HistoricoEntrega).where(HistoricoEntrega.entrega_id == delivery.id)) is not None
        from app.routers.rotas import _serialize_route_for_driver

        route_payload = _serialize_route_for_driver(db, route)
        receipt_payload = next(
            item["comprovante"] for item in route_payload["entregas"]
            if item["entrega_id"] == delivery.id
        )
        assert receipt_payload["nome_recebedor"] == "Maria"
        assert receipt_payload["documento_recebedor"] is None
        assert receipt_payload["criado_em"]


def test_atomic_completion_rejects_wrong_driver_without_changes(client):
    data = _create_route(client)

    response = client.post(
        f"/api/entregas/{data['delivery_id']}/concluir",
        headers=data["other_headers"],
        json={"nome_recebedor": "Maria"},
    )

    assert response.status_code == 403
    with SessionLocal() as db:
        delivery = db.get(Entrega, data["delivery_id"])
        assert delivery.status == StatusEntrega.EM_ROTA
        assert delivery.comprovante is None


@pytest.mark.parametrize("terminal", [StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA])
def test_atomic_completion_rejects_terminal_delivery(client, terminal):
    data = _create_route(client, delivery_status=terminal)

    response = client.post(
        f"/api/entregas/{data['delivery_id']}/concluir",
        headers=data["driver_headers"],
        json={"nome_recebedor": "Maria"},
    )

    assert response.status_code in {409, 422}
    with SessionLocal() as db:
        delivery = db.get(Entrega, data["delivery_id"])
        assert delivery.status == terminal
        assert delivery.comprovante is None


def test_atomic_completion_rolls_back_when_status_application_fails(client, monkeypatch):
    data = _create_route(client)
    from app.routers import entregas

    def fail_after_receipt(*args, **kwargs):
        raise RuntimeError("falha simulada antes do commit")

    monkeypatch.setattr(entregas, "apply_delivery_status", fail_after_receipt)

    response = client.post(
        f"/api/entregas/{data['delivery_id']}/concluir",
        headers=data["driver_headers"],
        json={"nome_recebedor": "Maria"},
    )

    assert response.status_code == 500
    with SessionLocal() as db:
        delivery = db.get(Entrega, data["delivery_id"])
        route = db.get(Rota, data["route_id"])
        assert delivery.comprovante is None
        assert delivery.status == StatusEntrega.EM_ROTA
        assert route.progresso_percentual == 0


def test_atomic_completion_reuses_existing_receipt(client):
    data = _create_route(client)
    receipt = client.post(
        f"/api/entregas/{data['delivery_id']}/comprovante",
        headers=data["driver_headers"],
        json={"nome_recebedor": "Antigo", "documento_recebedor": "123"},
    )
    assert receipt.status_code == 201, receipt.text

    response = client.post(
        f"/api/entregas/{data['delivery_id']}/concluir",
        headers=data["driver_headers"],
        json={"nome_recebedor": "Atualizado"},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        delivery = db.get(Entrega, data["delivery_id"])
        assert delivery.comprovante.nome_recebedor == "Atualizado"
        assert db.query(delivery.comprovante.__class__).filter_by(entrega_id=delivery.id).count() == 1


def test_driver_cannot_edit_or_delete_receipt_after_delivery(client):
    data = _create_route(client)
    completed = client.post(
        f"/api/entregas/{data['delivery_id']}/concluir",
        headers=data["driver_headers"],
        json={"nome_recebedor": "Maria"},
    )
    assert completed.status_code == 200, completed.text

    edited = client.put(
        f"/api/entregas/{data['delivery_id']}/comprovante",
        headers=data["driver_headers"],
        json={"nome_recebedor": "Outro"},
    )
    deleted = client.delete(
        f"/api/entregas/{data['delivery_id']}/comprovante",
        headers=data["driver_headers"],
    )
    assert edited.status_code in {409, 422}
    assert deleted.status_code in {409, 422}