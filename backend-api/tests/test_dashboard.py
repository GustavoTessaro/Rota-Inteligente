#tests/test_dashboard.py
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Cliente,
    Endereco,
    Entrega,
    Organizacao,
    Pedido,
    Rota,
    RotaEntrega,
    StatusEntrega,
    StatusPedido,
    StatusRota,
    StatusVeiculo,
    Usuario,
    Veiculo,
)


def _create_report_delivery(db, *, status, previsao_entrega, pedido_id, entregador_id, endereco_origem_id, endereco_destino_id):
    delivery = Entrega(
        pedido_id=pedido_id,
        entregador_id=entregador_id,
        endereco_origem_id=endereco_origem_id,
        endereco_destino_id=endereco_destino_id,
        status=status,
        previsao_entrega=previsao_entrega,
        data_coleta=previsao_entrega - timedelta(minutes=15) if previsao_entrega else None,
    )
    db.add(delivery)
    db.flush()
    return delivery


def test_dashboard_endpoint_returns_live_metrics(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        vehicle = db.scalar(select(Veiculo).order_by(Veiculo.id))
        assert vehicle is not None
        vehicle.status = StatusVeiculo.DISPONIVEL

        driver = db.scalar(select(Usuario).where(Usuario.perfil == "MOTORISTA").order_by(Usuario.id))
        assert driver is not None
        driver.ativo = True

        organization = db.get(Organizacao, vehicle.organizacao_id)
        order = db.scalar(select(Pedido).order_by(Pedido.id))
        assert order is not None
        order.organizacao_id = organization.id

        delayed_delivery = Entrega(
            pedido_id=order.id,
            entregador_id=driver.id,
            endereco_origem_id=1,
            endereco_destino_id=1,
            status=StatusEntrega.EM_ROTA,
            previsao_entrega=datetime.now() - timedelta(minutes=10),
            data_coleta=datetime.now() - timedelta(minutes=15),
            observacoes="atrasada",
        )
        db.add(delayed_delivery)
        db.commit()
        db.refresh(delayed_delivery)

        route = Rota(
            nome="Rota do dashboard",
            descricao="Rota criada pelo teste",
            organizacao_id=organization.id,
            veiculo_id=vehicle.id,
            motorista_id=driver.id,
            status=StatusRota.EM_EXECUCAO,
        )
        db.add(route)
        db.flush()
        db.add(RotaEntrega(rota_id=route.id, entrega_id=delayed_delivery.id, ordem_visita=1, sequencia_otimizada=1))
        db.commit()

    response = client.get('/api/relatorios/dashboard', headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data['entregas_andamento'] >= 1
    assert data['entregas_atrasadas'] >= 1
    assert data['rotas_em_execucao'] >= 1
    assert data['veiculos_disponiveis'] >= 1
    assert data['motoristas_ativos'] >= 1


def test_delivery_report_summary_uses_same_filtered_set(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        organization = db.scalar(select(Organizacao).order_by(Organizacao.id))
        assert organization is not None
        driver = db.scalar(select(Usuario).where(Usuario.perfil == "MOTORISTA").order_by(Usuario.id))
        assert driver is not None
        customer = db.scalar(select(Cliente).order_by(Cliente.id))
        assert customer is not None
        origin = db.scalar(select(Endereco).order_by(Endereco.id))
        assert origin is not None
        destination = db.scalar(select(Endereco).order_by(Endereco.id.desc()))
        assert destination is not None

        now = datetime.now()
        window_start = datetime(2035, 1, 15, 12, 0, 0)
        window_end = window_start + timedelta(minutes=10)
        for idx in range(5):
            order = Pedido(
                cliente_id=customer.id,
                organizacao_id=organization.id,
                endereco_entrega_id=destination.id,
                numero_pedido=f"PED-RESUMO-{idx + 1}",
                status=StatusPedido.ABERTO,
                criado_por=1,
                valor_total=Decimal("10.00"),
            )
            db.add(order)
            db.flush()

            status = [
                StatusEntrega.EM_ROTA,
                StatusEntrega.EM_ROTA,
                StatusEntrega.ENTREGUE,
                StatusEntrega.NAO_ENTREGUE,
                StatusEntrega.CANCELADA,
            ][idx]
            delivery = _create_report_delivery(
                db,
                status=status,
                previsao_entrega=(now + timedelta(hours=2)) if idx == 0 else (now - timedelta(hours=1)) if idx == 1 else (now - timedelta(hours=3)) if idx == 2 else (now - timedelta(hours=1)) if idx == 3 else (now - timedelta(hours=2)),
                pedido_id=order.id,
                entregador_id=driver.id,
                endereco_origem_id=origin.id,
                endereco_destino_id=destination.id,
            )
            delivery.criado_em = window_start + timedelta(minutes=idx)
            if status == StatusEntrega.ENTREGUE:
                delivery.data_entrega = now - timedelta(minutes=30)

        db.commit()

    response = client.get(
        "/api/relatorios/entregas?inicio={0}&fim={1}&status=EM_ROTA".format(
            window_start.isoformat(),
            window_end.isoformat(),
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert data["entregas_atrasadas"] == 1
    assert data["entregas_em_dia"] == 1
    assert any(item["status"] == "EM_ROTA" and item["quantidade"] == 2 for item in data["entregas_por_status"])


def test_delivery_report_summary_ignores_terminal_and_null_deadlines(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        organization = db.scalar(select(Organizacao).order_by(Organizacao.id))
        assert organization is not None
        driver = db.scalar(select(Usuario).where(Usuario.perfil == "MOTORISTA").order_by(Usuario.id))
        assert driver is not None
        customer = db.scalar(select(Cliente).order_by(Cliente.id))
        assert customer is not None
        origin = db.scalar(select(Endereco).order_by(Endereco.id))
        assert origin is not None
        destination = db.scalar(select(Endereco).order_by(Endereco.id.desc()))
        assert destination is not None

        now = datetime.now()
        window_start = datetime(2036, 2, 10, 9, 0, 0)
        window_end = window_start + timedelta(minutes=10)
        for idx, status in enumerate([
            StatusEntrega.ENTREGUE,
            StatusEntrega.NAO_ENTREGUE,
            StatusEntrega.CANCELADA,
            StatusEntrega.AGUARDANDO_COLETA,
        ]):
            order = Pedido(
                cliente_id=customer.id,
                organizacao_id=organization.id,
                endereco_entrega_id=destination.id,
                numero_pedido=f"PED-NULL-{idx + 1}",
                status=StatusPedido.ABERTO,
                criado_por=1,
                valor_total=Decimal("10.00"),
            )
            db.add(order)
            db.flush()
            delivery = _create_report_delivery(
                db,
                status=status,
                previsao_entrega=(now - timedelta(hours=1)) if status in {StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA} else None,
                pedido_id=order.id,
                entregador_id=driver.id,
                endereco_origem_id=origin.id,
                endereco_destino_id=destination.id,
            )
            delivery.criado_em = window_start + timedelta(minutes=idx)

        db.commit()

    response = client.get(
        "/api/relatorios/entregas?inicio={0}&fim={1}".format(
            window_start.isoformat(),
            window_end.isoformat(),
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["entregas_atrasadas"] == 0
    assert data["entregas_em_dia"] == 0
    assert all(item["quantidade"] >= 0 for item in data["entregas_por_status"])


def test_delivery_report_average_duration_uses_eligible_rows(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        organization = db.scalar(select(Organizacao).order_by(Organizacao.id))
        assert organization is not None
        driver = db.scalar(select(Usuario).where(Usuario.perfil == "MOTORISTA").order_by(Usuario.id))
        assert driver is not None
        customer = db.scalar(select(Cliente).order_by(Cliente.id))
        assert customer is not None
        origin = db.scalar(select(Endereco).order_by(Endereco.id))
        assert origin is not None
        destination = db.scalar(select(Endereco).order_by(Endereco.id.desc()))
        assert destination is not None

        window_start = datetime(2037, 4, 1, 8, 0, 0)
        window_end = datetime(2037, 4, 1, 18, 0, 0)
        deliveries = [
            {"status": StatusEntrega.EM_ROTA, "data_coleta": window_start + timedelta(hours=1), "data_entrega": window_start + timedelta(hours=2, minutes=30)},
            {"status": StatusEntrega.EM_ROTA, "data_coleta": window_start + timedelta(hours=3), "data_entrega": window_start + timedelta(hours=4)},
            {"status": StatusEntrega.EM_ROTA, "data_coleta": window_start + timedelta(hours=5), "data_entrega": window_start + timedelta(hours=6, minutes=30)},
            {"status": StatusEntrega.EM_ROTA, "data_coleta": None, "data_entrega": window_start + timedelta(hours=7)},
            {"status": StatusEntrega.EM_ROTA, "data_coleta": window_start + timedelta(hours=8), "data_entrega": window_start + timedelta(hours=7, minutes=30)},
            {"status": StatusEntrega.AGUARDANDO_COLETA, "data_coleta": window_start + timedelta(hours=9), "data_entrega": window_start + timedelta(hours=10)},
        ]

        for idx, payload in enumerate(deliveries):
            order = Pedido(
                cliente_id=customer.id,
                organizacao_id=organization.id,
                endereco_entrega_id=destination.id,
                numero_pedido=f"PED-TEMPO-{idx + 1}",
                status=StatusPedido.ABERTO,
                criado_por=1,
                valor_total=Decimal("10.00"),
            )
            db.add(order)
            db.flush()

            delivery = Entrega(
                pedido_id=order.id,
                entregador_id=driver.id,
                endereco_origem_id=origin.id,
                endereco_destino_id=destination.id,
                status=payload["status"],
                previsao_entrega=window_start + timedelta(hours=12),
                data_coleta=payload["data_coleta"],
                data_entrega=payload["data_entrega"],
            )
            delivery.criado_em = window_start + timedelta(minutes=idx)
            db.add(delivery)

        db.commit()

    response = client.get(
        "/api/relatorios/entregas?inicio={0}&fim={1}&status=EM_ROTA".format(
            window_start.isoformat(),
            window_end.isoformat(),
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 5
    assert data["tempo_medio_minutos"] == 80.0


def test_delivery_report_average_duration_returns_zero_when_no_eligible_records(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        organization = db.scalar(select(Organizacao).order_by(Organizacao.id))
        assert organization is not None
        driver = db.scalar(select(Usuario).where(Usuario.perfil == "MOTORISTA").order_by(Usuario.id))
        assert driver is not None
        customer = db.scalar(select(Cliente).order_by(Cliente.id))
        assert customer is not None
        origin = db.scalar(select(Endereco).order_by(Endereco.id))
        assert origin is not None
        destination = db.scalar(select(Endereco).order_by(Endereco.id.desc()))
        assert destination is not None

        window_start = datetime(2037, 5, 3, 9, 0, 0)
        window_end = datetime(2037, 5, 3, 19, 0, 0)
        for idx in range(2):
            order = Pedido(
                cliente_id=customer.id,
                organizacao_id=organization.id,
                endereco_entrega_id=destination.id,
                numero_pedido=f"PED-TEMPO-ZERO-{idx + 1}",
                status=StatusPedido.ABERTO,
                criado_por=1,
                valor_total=Decimal("10.00"),
            )
            db.add(order)
            db.flush()

            delivery = Entrega(
                pedido_id=order.id,
                entregador_id=driver.id,
                endereco_origem_id=origin.id,
                endereco_destino_id=destination.id,
                status=StatusEntrega.EM_ROTA,
                previsao_entrega=window_start + timedelta(hours=2),
                data_coleta=None,
                data_entrega=None,
            )
            delivery.criado_em = window_start + timedelta(minutes=idx)
            db.add(delivery)

        db.commit()

    response = client.get(
        "/api/relatorios/entregas?inicio={0}&fim={1}&status=EM_ROTA".format(
            window_start.isoformat(),
            window_end.isoformat(),
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["tempo_medio_minutos"] == 0


def test_delivery_report_driver_distribution_uses_filtered_set(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        organization = db.scalar(select(Organizacao).order_by(Organizacao.id))
        assert organization is not None
        driver_a = db.scalar(select(Usuario).where(Usuario.perfil == "MOTORISTA").order_by(Usuario.id))
        assert driver_a is not None
        driver_b = db.scalar(
            select(Usuario).where(Usuario.perfil == "MOTORISTA").where(Usuario.id != driver_a.id).order_by(Usuario.id)
        )
        if driver_b is None:
            driver_b = driver_a
        customer = db.scalar(select(Cliente).order_by(Cliente.id))
        assert customer is not None
        origin = db.scalar(select(Endereco).order_by(Endereco.id))
        assert origin is not None
        destination = db.scalar(select(Endereco).order_by(Endereco.id.desc()))
        assert destination is not None

        window_start = datetime(2037, 6, 10, 8, 0, 0)
        window_end = datetime(2037, 6, 10, 18, 0, 0)
        entries = [
            (driver_a.id, StatusEntrega.EM_ROTA, 1),
            (driver_a.id, StatusEntrega.EM_ROTA, 2),
            (driver_b.id, StatusEntrega.EM_ROTA, 3),
            (driver_b.id, StatusEntrega.ENTREGUE, 4),
            (driver_b.id, StatusEntrega.EM_ROTA, 5),
        ]

        for idx, (driver_id, status, order_number) in enumerate(entries):
            order = Pedido(
                cliente_id=customer.id,
                organizacao_id=organization.id,
                endereco_entrega_id=destination.id,
                numero_pedido=f"PED-DRIVER-{idx + 1}",
                status=StatusPedido.ABERTO,
                criado_por=1,
                valor_total=Decimal("10.00"),
            )
            db.add(order)
            db.flush()

            delivery = Entrega(
                pedido_id=order.id,
                entregador_id=driver_id,
                endereco_origem_id=origin.id,
                endereco_destino_id=destination.id,
                status=status,
                previsao_entrega=window_start + timedelta(hours=2),
                data_coleta=window_start + timedelta(hours=1),
                data_entrega=window_start + timedelta(hours=2),
            )
            delivery.criado_em = window_start + timedelta(minutes=idx)
            db.add(delivery)

        db.commit()

    response = client.get(
        "/api/relatorios/entregas?inicio={0}&fim={1}&status=EM_ROTA".format(
            window_start.isoformat(),
            window_end.isoformat(),
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 4
    assert any(item["motorista_id"] == driver_a.id and item["quantidade"] == 2 for item in data["entregas_por_motorista"])
    assert any(item["motorista_id"] == driver_b.id and item["quantidade"] == 2 for item in data["entregas_por_motorista"])


def test_delivery_report_organization_distribution_uses_filtered_set(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        organization_a = db.scalar(select(Organizacao).order_by(Organizacao.id))
        assert organization_a is not None
        organization_b = db.scalar(
            select(Organizacao).where(Organizacao.id != organization_a.id).order_by(Organizacao.id)
        )
        if organization_b is None:
            organization_b = organization_a
        driver = db.scalar(select(Usuario).where(Usuario.perfil == "MOTORISTA").order_by(Usuario.id))
        assert driver is not None
        customer = db.scalar(select(Cliente).order_by(Cliente.id))
        assert customer is not None
        origin = db.scalar(select(Endereco).order_by(Endereco.id))
        assert origin is not None
        destination = db.scalar(select(Endereco).order_by(Endereco.id.desc()))
        assert destination is not None

        window_start = datetime(2037, 7, 5, 8, 0, 0)
        window_end = datetime(2037, 7, 5, 18, 0, 0)
        for idx, (organization, status) in enumerate([
            (organization_a, StatusEntrega.EM_ROTA),
            (organization_a, StatusEntrega.EM_ROTA),
            (organization_b, StatusEntrega.ENTREGUE),
            (organization_b, StatusEntrega.EM_ROTA),
        ]):
            order = Pedido(
                cliente_id=customer.id,
                organizacao_id=organization.id,
                endereco_entrega_id=destination.id,
                numero_pedido=f"PED-ORG-{idx + 1}",
                status=StatusPedido.ABERTO,
                criado_por=1,
                valor_total=Decimal("10.00"),
            )
            db.add(order)
            db.flush()

            delivery = Entrega(
                pedido_id=order.id,
                entregador_id=driver.id,
                endereco_origem_id=origin.id,
                endereco_destino_id=destination.id,
                status=status,
                previsao_entrega=window_start + timedelta(hours=2),
                data_coleta=window_start + timedelta(hours=1),
                data_entrega=window_start + timedelta(hours=2),
            )
            delivery.criado_em = window_start + timedelta(minutes=idx)
            db.add(delivery)

        db.commit()

    response = client.get(
        "/api/relatorios/entregas?inicio={0}&fim={1}&status=EM_ROTA".format(
            window_start.isoformat(),
            window_end.isoformat(),
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 3
    org_summary = {item["organizacao_id"]: item for item in data["entregas_por_organizacao"]}
    assert org_summary[organization_a.id]["quantidade_total_pedidos"] == 2
    assert org_summary[organization_a.id]["distribuicao_por_status"][0]["quantidade"] == 2
    assert org_summary[organization_b.id]["quantidade_total_pedidos"] == 1
    assert org_summary[organization_b.id]["distribuicao_por_status"][0]["quantidade"] == 1
