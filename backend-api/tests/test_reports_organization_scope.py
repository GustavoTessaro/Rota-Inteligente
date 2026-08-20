from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

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
    StatusEntrega,
    StatusPedido,
    StatusRota,
    StatusVeiculo,
    TipoVeiculo,
    Usuario,
    Veiculo,
)
from app.security import create_token, hash_password


PASSWORD = "123456"


def _login(client, email):
    with SessionLocal() as db:
        user = db.scalar(select(Usuario).where(Usuario.email == email))
        assert user is not None
        return {"Authorization": f"Bearer {create_token(user)}"}


def _seed_organization(db, suffix, now):
    organization = Organizacao(
        nome=f"Organização {suffix}",
        cnpj=f"90000000000{suffix}",
        email=f"org{suffix}@example.com",
        telefone="11999999999",
        endereco=f"Rua {suffix}",
    )
    db.add(organization)
    db.flush()
    manager = Usuario(
        nome=f"Gestor {suffix}",
        email=f"gestor{suffix}@example.com",
        senha_hash=hash_password(PASSWORD),
        perfil=Perfil.GESTOR,
        ativo=True,
        organizacao_id=organization.id,
    )
    driver = Usuario(
        nome=f"Motorista {suffix}",
        email=f"driver{suffix}@example.com",
        senha_hash=hash_password(PASSWORD),
        perfil=Perfil.MOTORISTA,
        ativo=True,
        organizacao_id=organization.id,
    )
    db.add_all([manager, driver])
    db.flush()
    vehicle = Veiculo(
        organizacao_id=organization.id,
        motorista_id=driver.id,
        placa=f"{suffix}1234",
        modelo="Ducato",
        marca="Fiat",
        ano=2024,
        cor="Branco",
        tipo=TipoVeiculo.VAN,
        status=StatusVeiculo.DISPONIVEL,
        ativo=True,
    )
    customer = Cliente(nome=f"Cliente {suffix}", cpf_cnpj=f"{suffix}00000000000")
    db.add_all([vehicle, customer])
    db.flush()
    address = Endereco(
        cliente_id=customer.id,
        organizacao_id=organization.id,
        logradouro=f"Rua {suffix}",
        numero="10",
        bairro="Centro",
        cidade="Lages",
        estado="SC",
        cep="88500000",
        latitude=Decimal("-27.81"),
        longitude=Decimal("-50.32"),
        principal=True,
    )
    db.add(address)
    db.flush()
    organization.endereco_id = address.id
    delivered_order = Pedido(
        cliente_id=customer.id,
        organizacao_id=organization.id,
        endereco_entrega_id=address.id,
        numero_pedido=f"PED-{suffix}-ENTREGUE",
        status=StatusPedido.FINALIZADO,
        criado_por=manager.id,
    )
    active_order = Pedido(
        cliente_id=customer.id,
        organizacao_id=organization.id,
        endereco_entrega_id=address.id,
        numero_pedido=f"PED-{suffix}-ATIVO",
        status=StatusPedido.ABERTO,
        criado_por=manager.id,
    )
    db.add_all([delivered_order, active_order])
    db.flush()
    delivered = Entrega(
        pedido_id=delivered_order.id,
        entregador_id=driver.id,
        endereco_origem_id=address.id,
        endereco_destino_id=address.id,
        status=StatusEntrega.ENTREGUE,
        data_entrega=now - timedelta(minutes=5),
    )
    active = Entrega(
        pedido_id=active_order.id,
        entregador_id=driver.id,
        endereco_origem_id=address.id,
        endereco_destino_id=address.id,
        status=StatusEntrega.EM_ROTA,
        previsao_entrega=now - timedelta(minutes=10),
    )
    db.add_all([delivered, active])
    db.flush()
    active_route = Rota(
        nome=f"Rota {suffix} em execução",
        descricao="Teste de escopo",
        organizacao_id=organization.id,
        motorista_id=driver.id,
        veiculo_id=vehicle.id,
        status=StatusRota.EM_EXECUCAO,
        data_planejada=now,
    )
    planned_route = Rota(
        nome=f"Rota {suffix} planejada",
        descricao="Teste de escopo",
        organizacao_id=organization.id,
        motorista_id=driver.id,
        veiculo_id=vehicle.id,
        status=StatusRota.PRONTA,
        data_planejada=now + timedelta(hours=1),
    )
    db.add_all([active_route, planned_route])
    db.flush()
    db.add(RotaEntrega(rota_id=active_route.id, entrega_id=active.id, ordem_visita=1, sequencia_otimizada=1))
    db.commit()
    return {"organization": organization, "manager": manager, "driver": driver, "vehicle": vehicle}


@pytest.fixture()
def scoped_report_data(client):
    now = datetime.now()
    with SessionLocal() as db:
        org_a = _seed_organization(db, "A", now)
        org_b = _seed_organization(db, "B", now)
    return org_a, org_b


def test_admin_sees_both_organizations(client, admin_headers, scoped_report_data):
    response = client.get("/api/relatorios/dashboard", headers=admin_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert {item["nome"] for item in data["entregas_por_motorista"]} >= {"Motorista A", "Motorista B"}
    assert {item["nome"] for item in data["entregas_por_veiculo"]} >= {"A1234", "B1234"}
    assert {item["nome"] for item in data["proximas_rotas"]} >= {"Rota A planejada", "Rota B planejada"}


@pytest.mark.parametrize("suffix,other_suffix", [("A", "B"), ("B", "A")])
def test_manager_sees_only_own_organization(client, scoped_report_data, suffix, other_suffix):
    organizations = scoped_report_data
    current = next(item for item in organizations if item["manager"].email == f"gestor{suffix}@example.com")
    response = client.get("/api/relatorios/dashboard", headers=_login(client, current["manager"].email))
    assert response.status_code == 200, response.text
    data = response.json()
    assert {item["nome"] for item in data["entregas_por_motorista"]} == {f"Motorista {suffix}"}
    assert {item["nome"] for item in data["entregas_por_veiculo"]} == {f"{suffix}1234"}
    assert {item["nome"] for item in data["proximas_rotas"]} == {f"Rota {suffix} planejada"}
    assert data["motoristas_ativos"] == 1
    assert data["veiculos_disponiveis"] == 1


def test_driver_is_rejected_from_managerial_reports(client, scoped_report_data):
    driver = scoped_report_data[0]["driver"]
    headers = _login(client, driver.email)
    assert client.get("/api/relatorios/dashboard", headers=headers).status_code == 403
    assert client.get("/api/relatorios/entregas", headers=headers).status_code == 403


def test_manager_delivery_report_is_scoped_and_client_scope_parameter_cannot_escape(client, scoped_report_data):
    org_a, org_b = scoped_report_data
    headers = _login(client, org_a["manager"].email)
    response = client.get("/api/relatorios/entregas?organizacao_id=%s" % org_b["organization"].id, headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()["entregas"]
    assert rows
    with SessionLocal() as db:
        order_ids = {row["pedido_id"] for row in rows}
        organizations = db.scalars(select(Pedido.organizacao_id).where(Pedido.id.in_(order_ids))).all()
    assert set(organizations) == {org_a["organization"].id}


def test_manager_metrics_are_scoped_for_status_counts_and_evolution(client, scoped_report_data):
    org_a, org_b = scoped_report_data
    data_a = client.get("/api/relatorios/dashboard", headers=_login(client, org_a["manager"].email)).json()
    data_b = client.get("/api/relatorios/dashboard", headers=_login(client, org_b["manager"].email)).json()
    assert data_a["entregas_hoje"] == data_b["entregas_hoje"] == 2
    assert data_a["entregas_concluidas"] == data_b["entregas_concluidas"] == 1
    assert data_a["entregas_andamento"] == data_b["entregas_andamento"] == 1
    assert sum(item["quantidade"] for item in data_a["entregas_por_status"]) == 2
    assert sum(item["quantidade"] for item in data_b["entregas_por_status"]) == 2
    assert [item["quantidade"] for item in data_a["evolucao_diaria_entregas"]] == [item["quantidade"] for item in data_b["evolucao_diaria_entregas"]]
