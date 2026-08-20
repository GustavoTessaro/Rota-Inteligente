from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Endereco,
    Entrega,
    HistoricoEntrega,
    Organizacao,
    Perfil,
    Pedido,
    Rota,
    RotaEntrega,
    StatusEntrega,
    StatusRota,
    Usuario,
    Veiculo,
)


def _login(client, email, password="123456"):
    response = client.post("/api/auth/login", json={"email": email, "senha": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _driver_and_context():
    with SessionLocal() as db:
        driver = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA).order_by(Usuario.id))
        organization = db.get(Organizacao, driver.organizacao_id)
        address = db.scalar(select(Endereco).order_by(Endereco.id))
        pedido = db.scalar(select(Pedido).order_by(Pedido.id))
        vehicle = db.scalar(select(Veiculo).where(Veiculo.organizacao_id == organization.id).order_by(Veiculo.id))
        return driver, organization, address, pedido, vehicle


def _create_delivery(db, driver, address, pedido, status, delivered_at=None):
    delivery = Entrega(
        pedido_id=pedido.id,
        entregador_id=driver.id,
        endereco_origem_id=address.id,
        endereco_destino_id=address.id,
        status=status,
        data_entrega=delivered_at,
    )
    db.add(delivery)
    db.flush()
    return delivery


def _create_route(db, driver, organization, status, now, vehicle=None, **metrics):
    route = Rota(
        nome=f"Resumo {status.value}",
        descricao="Teste resumo diário",
        organizacao_id=organization.id,
        motorista_id=driver.id,
        veiculo_id=vehicle.id if vehicle else None,
        status=status,
        data_inicio=metrics.get("data_inicio"),
        data_conclusao=metrics.get("data_conclusao"),
        distancia_prevista=metrics.get("distancia_prevista", Decimal("0")),
        distancia_real=metrics.get("distancia_real", Decimal("0")),
        duracao_prevista=metrics.get("duracao_prevista", Decimal("0")),
        duracao_real=metrics.get("duracao_real", Decimal("0")),
        progresso_percentual=metrics.get("progresso_percentual", 0),
    )
    db.add(route)
    db.flush()
    return route


def _link_delivery(db, route, delivery):
    db.add(RotaEntrega(rota_id=route.id, entrega_id=delivery.id, ordem_visita=1, sequencia_otimizada=1))


def _add_delivery_history(db, delivery, status, created_at, driver_id):
    db.add(HistoricoEntrega(
        entrega_id=delivery.id,
        status_anterior=StatusEntrega.EM_ROTA.value,
        status_novo=status.value,
        observacao="Teste de histórico",
        alterado_por=driver_id,
        criado_em=created_at,
    ))


def _summary(client, driver):
    return client.get("/api/rotas/motorista/resumo-diario", headers=_login(client, driver.email))


def test_driver_without_active_route_returns_zero_summary(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    response = _summary(client, driver)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["entregas_concluidas_hoje"] == 0
    assert data["entregas_nao_entregues_hoje"] == 0
    assert data["entregas_pendentes"] == 0
    assert data["rotas_concluidas_hoje"] == 0
    assert data["distancia_hoje_km"] == 0
    assert data["tempo_em_rota_hoje_minutos"] == 0
    assert data["rota_atual"] is None


def test_daily_summary_counts_only_today_and_prefers_real_distance(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    now = datetime.now()
    with SessionLocal() as db:
        route = _create_route(
            db, driver, organization, StatusRota.FINALIZADA, now, vehicle,
            data_inicio=now - timedelta(minutes=42), data_conclusao=now,
            distancia_prevista=Decimal("20"), distancia_real=Decimal("8.4"),
            duracao_prevista=Decimal("2"), duracao_real=Decimal("1.7"),
        )
        for _ in range(3):
            delivery = _create_delivery(db, driver, address, pedido, StatusEntrega.ENTREGUE, now)
            _link_delivery(db, route, delivery)
        old_delivery = _create_delivery(db, driver, address, pedido, StatusEntrega.ENTREGUE, now - timedelta(days=1))
        old_route = _create_route(
            db, driver, organization, StatusRota.FINALIZADA, now - timedelta(days=1),
            distancia_prevista=Decimal("99"), distancia_real=Decimal("50"),
            data_inicio=now - timedelta(days=1, minutes=20), data_conclusao=now - timedelta(days=1),
        )
        _link_delivery(db, old_route, old_delivery)
        db.commit()

    data = _summary(client, driver).json()
    assert data["rotas_concluidas_hoje"] == 1
    assert data["entregas_concluidas_hoje"] == 3
    assert data["distancia_hoje_km"] == pytest.approx(8.4)
    assert data["tempo_em_rota_hoje_minutos"] == 102


def test_daily_summary_counts_not_delivered_from_history_with_null_delivery_date(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    now = datetime.now()
    with SessionLocal() as db:
        route = _create_route(db, driver, organization, StatusRota.FINALIZADA, now, data_conclusao=now)
        today = _create_delivery(db, driver, address, pedido, StatusEntrega.NAO_ENTREGUE, None)
        old = _create_delivery(db, driver, address, pedido, StatusEntrega.NAO_ENTREGUE, None)
        _link_delivery(db, route, today)
        _link_delivery(db, route, old)
        _add_delivery_history(db, today, StatusEntrega.NAO_ENTREGUE, now, driver.id)
        _add_delivery_history(db, old, StatusEntrega.NAO_ENTREGUE, now - timedelta(days=1), driver.id)
        db.commit()

    data = _summary(client, driver).json()
    assert data["entregas_nao_entregues_hoje"] == 1


def test_daily_summary_deduplicates_duplicate_not_delivered_history(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    now = datetime.now()
    with SessionLocal() as db:
        route = _create_route(db, driver, organization, StatusRota.FINALIZADA, now, data_conclusao=now)
        delivery = _create_delivery(db, driver, address, pedido, StatusEntrega.NAO_ENTREGUE, None)
        _link_delivery(db, route, delivery)
        _add_delivery_history(db, delivery, StatusEntrega.NAO_ENTREGUE, now, driver.id)
        _add_delivery_history(db, delivery, StatusEntrega.NAO_ENTREGUE, now + timedelta(minutes=1), driver.id)
        db.commit()

    assert _summary(client, driver).json()["entregas_nao_entregues_hoje"] == 1


def test_daily_summary_ignores_not_delivered_history_for_other_driver(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    now = datetime.now()
    with SessionLocal() as db:
        other = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA, Usuario.id != driver.id).order_by(Usuario.id))
        route = _create_route(db, driver, organization, StatusRota.FINALIZADA, now, data_conclusao=now)
        delivery = _create_delivery(db, other, address, pedido, StatusEntrega.NAO_ENTREGUE, None)
        _link_delivery(db, route, delivery)
        _add_delivery_history(db, delivery, StatusEntrega.NAO_ENTREGUE, now, other.id)
        db.commit()

    assert _summary(client, driver).json()["entregas_nao_entregues_hoje"] == 0


def test_daily_summary_ignores_other_delivery_history_status(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    now = datetime.now()
    with SessionLocal() as db:
        route = _create_route(db, driver, organization, StatusRota.FINALIZADA, now, data_conclusao=now)
        delivery = _create_delivery(db, driver, address, pedido, StatusEntrega.EM_ROTA, None)
        _link_delivery(db, route, delivery)
        _add_delivery_history(db, delivery, StatusEntrega.EM_ROTA, now, driver.id)
        db.commit()

    assert _summary(client, driver).json()["entregas_nao_entregues_hoje"] == 0


def test_distance_falls_back_to_expected_and_duration_to_elapsed_time(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    now = datetime.now()
    with SessionLocal() as db:
        _create_route(
            db, driver, organization, StatusRota.FINALIZADA, now,
            distancia_prevista=Decimal("12.5"), distancia_real=Decimal("0"),
            duracao_prevista=Decimal("3"), duracao_real=Decimal("0"),
            data_inicio=now - timedelta(minutes=35), data_conclusao=now,
        )
        db.commit()

    data = _summary(client, driver).json()
    assert data["distancia_hoje_km"] == pytest.approx(12.5)
    assert data["tempo_em_rota_hoje_minutos"] == 35


def test_real_duration_has_priority_over_elapsed_time(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    now = datetime.now()
    with SessionLocal() as db:
        _create_route(
            db, driver, organization, StatusRota.FINALIZADA, now,
            duracao_prevista=Decimal("3"), duracao_real=Decimal("0.4"),
            data_inicio=now - timedelta(minutes=90), data_conclusao=now,
        )
        db.commit()

    assert _summary(client, driver).json()["tempo_em_rota_hoje_minutos"] == 24


def test_pending_deliveries_are_limited_to_current_operational_routes(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    now = datetime.now()
    with SessionLocal() as db:
        active_route = _create_route(db, driver, organization, StatusRota.PAUSADA, now)
        cancelled_route = _create_route(db, driver, organization, StatusRota.CANCELADA, now)
        orphan = _create_delivery(db, driver, address, pedido, StatusEntrega.EM_ROTA)
        active = _create_delivery(db, driver, address, pedido, StatusEntrega.EM_ROTA)
        cancelled = _create_delivery(db, driver, address, pedido, StatusEntrega.EM_ROTA)
        _link_delivery(db, active_route, active)
        _link_delivery(db, cancelled_route, cancelled)
        db.commit()

    assert _summary(client, driver).json()["entregas_pendentes"] == 1


@pytest.mark.parametrize("status", [StatusRota.PRONTA, StatusRota.EM_EXECUCAO, StatusRota.PAUSADA])
def test_current_route_statuses_are_returned(client, status):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    with SessionLocal() as db:
        _create_route(db, driver, organization, status, datetime.now(), vehicle)
        db.commit()

    data = _summary(client, driver).json()
    assert data["rota_atual"] is not None
    assert data["rota_atual"]["status"] == status.value


def test_current_route_vehicle_has_priority_over_driver_vehicle(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    with SessionLocal() as db:
        route = _create_route(db, driver, organization, StatusRota.PRONTA, datetime.now(), vehicle)
        db.commit()

    data = _summary(client, driver).json()
    assert data["veiculo_atual"]["id"] == vehicle.id
    assert data["rota_atual"]["id"] == route.id


def test_linked_driver_vehicle_is_returned_without_active_route(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    with SessionLocal() as db:
        active_routes = db.scalars(select(Rota).where(Rota.motorista_id == driver.id, Rota.status.in_([StatusRota.PRONTA, StatusRota.EM_EXECUCAO, StatusRota.PAUSADA]))).all()
        for route in active_routes:
            route.status = StatusRota.FINALIZADA
        db.commit()

    data = _summary(client, driver).json()
    assert data["rota_atual"] is None
    assert data["veiculo_atual"]["id"] == vehicle.id


def test_summary_is_scoped_to_authenticated_driver(client):
    driver, organization, address, pedido, vehicle = _driver_and_context()
    with SessionLocal() as db:
        other = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA, Usuario.id != driver.id).order_by(Usuario.id))
        _create_route(db, other, organization, StatusRota.FINALIZADA, datetime.now(), distancia_real=Decimal("77"), data_conclusao=datetime.now())
        db.commit()

    data = _summary(client, driver).json()
    assert data["distancia_hoje_km"] == 0


def test_non_driver_cannot_access_driver_daily_summary(client, admin_headers):
    response = client.get("/api/rotas/motorista/resumo-diario", headers=admin_headers)
    assert response.status_code == 403
