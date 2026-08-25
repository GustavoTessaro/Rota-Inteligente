from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    Cliente,
    Endereco,
    Entrega,
    Organizacao,
    Pedido,
    Perfil,
    Rota,
    RotaEntrega,
    RotaPosicao,
    StatusEntrega,
    StatusRota,
    StatusVeiculo,
    Usuario,
    Veiculo,
)
from app.seed_tracking_homologacao import prepare_tracking_homologacao
from app.seed_homologacao import prepare_homologacao


@pytest.fixture()
def prepared_tracking(client):
    geocode_result = lambda db, address: {
        "success": True,
        "latitude": Decimal("-27.81"),
        "longitude": Decimal("-50.32"),
        "endereco_formatado": f"{address.logradouro}, {address.numero}, Lages - SC",
        "place_id": "tracking-test",
    }
    with patch("app.seed_homologacao.geocode_address", side_effect=geocode_result), patch("app.seed_tracking_homologacao.geocode_address", side_effect=geocode_result):
        with SessionLocal() as db:
            prepare_homologacao(db)
            organization = db.scalar(select(Organizacao).where(Organizacao.nome == "Angeloni"))
            manager = db.scalar(select(Usuario).where(Usuario.email == "gestor1@sistema.com"))
            manager.organizacao_id = organization.id
            db.flush()
            result = prepare_tracking_homologacao(db)
    return result


def test_prepare_creates_two_isolated_tracking_scenarios(prepared_tracking):
    with SessionLocal() as db:
        routes = db.scalars(select(Rota).where(Rota.nome.in_([
            "Rota Homologação Tracking A",
            "Rota Homologação Tracking B",
        ])).order_by(Rota.nome)).all()
        assert len(routes) == 2
        route_a = next(route for route in routes if route.organizacao_id == 3)
        route_b = next(route for route in routes if route.organizacao_id == 2)
        assert route_a.status == route_b.status == StatusRota.PRONTA
        assert route_a.carga_confirmada is False
        assert route_b.carga_confirmada is False
        assert route_a.data_inicio is None and route_b.data_inicio is None
        assert route_a.data_conclusao is None and route_b.data_conclusao is None
        assert route_a.motorista_id == 4
        assert route_b.motorista_id == 6
        assert route_a.veiculo_id == 1
        assert route_b.veiculo.placa == "TRKB1234"
        assert route_b.veiculo.organizacao_id == 2
        assert route_b.veiculo.motorista_id == 6
        for route in routes:
            assert len(route.entregas) == 1
            assert route.entregas[0].entrega.status == StatusEntrega.AGUARDANDO_COLETA
            assert route.entregas[0].entrega.pedido.organizacao_id == route.organizacao_id
        assert db.scalar(select(func.count()).select_from(RotaPosicao)) == 0


def test_prepare_reuses_stable_entities_without_duplicates(prepared_tracking):
    with patch("app.seed_tracking_homologacao.geocode_address", return_value={"success": True, "latitude": -27.81, "longitude": -50.32}):
        with SessionLocal() as db:
            first = prepare_tracking_homologacao(db)
            second = prepare_tracking_homologacao(db)
    assert first["routes"]["A"].id == second["routes"]["A"].id
    assert first["routes"]["B"].id == second["routes"]["B"].id
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Veiculo).where(Veiculo.placa == "TRKB1234")) == 1
        assert db.scalar(select(func.count()).select_from(Cliente).where(Cliente.nome.in_(["TRACKING CLIENTE A", "TRACKING CLIENTE B"]))) == 2
        assert db.scalar(select(func.count()).select_from(Pedido).where(Pedido.numero_pedido.in_(["PED-TRACKING-A", "PED-TRACKING-B"]))) == 2
        assert db.scalar(select(func.count()).select_from(Rota).where(Rota.nome.in_(["Rota Homologação Tracking A", "Rota Homologação Tracking B"]))) == 2


def test_prepare_preserves_existing_operational_and_historical_routes(prepared_tracking):
    with SessionLocal() as db:
        route_a = db.scalar(select(Rota).where(Rota.nome == "Rota Homologação Tracking A"))
        route_a.status = StatusRota.EM_EXECUCAO
        route_a.carga_confirmada = True
        route_b = db.scalar(select(Rota).where(Rota.nome == "Rota Homologação Tracking B"))
        route_b.status = StatusRota.FINALIZADA
        db.commit()
        original_a = (route_a.id, route_a.status, route_a.carga_confirmada)
        original_b = (route_b.id, route_b.status)

    with patch("app.seed_tracking_homologacao.geocode_address", return_value={"success": True, "latitude": -27.81, "longitude": -50.32}):
        with SessionLocal() as db:
            result = prepare_tracking_homologacao(db)

    assert result["protected"]["A"].id == original_a[0]
    assert result["routes"]["B"].id != original_b[0]
    with SessionLocal() as db:
        assert (db.get(Rota, original_a[0]).status, db.get(Rota, original_a[0]).carga_confirmada) == (StatusRota.EM_EXECUCAO, True)
        assert db.get(Rota, original_b[0]).status == StatusRota.FINALIZADA
        assert db.scalar(select(func.count()).select_from(Rota).where(Rota.nome == "Rota Homologação Tracking B #2")) == 1


def test_prepare_creates_suffix_after_terminal_route(prepared_tracking):
    with SessionLocal() as db:
        for route in db.scalars(select(Rota).where(Rota.nome.in_([
            "Rota Homologação Tracking A",
            "Rota Homologação Tracking B",
        ]))).all():
            route.status = StatusRota.CANCELADA
        db.commit()

    with patch("app.seed_tracking_homologacao.geocode_address", return_value={"success": True, "latitude": -27.81, "longitude": -50.32}):
        with SessionLocal() as db:
            result = prepare_tracking_homologacao(db)

    assert result["routes"]["A"].nome == "Rota Homologação Tracking A #2"
    assert result["routes"]["B"].nome == "Rota Homologação Tracking B #2"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RotaPosicao)) == 0
        assert db.scalar(select(func.count()).select_from(Rota).where(Rota.status == StatusRota.EM_EXECUCAO)) == 0
