from decimal import Decimal

from sqlalchemy import select

from app import seed_homologacao
from app.database import SessionLocal
from app.models import Cliente, Endereco, Organizacao, Pedido, Rota, Usuario, Veiculo


def _fake_geocode(db, address):
    address.latitude = Decimal("-27.815000")
    address.longitude = Decimal("-50.325000")
    address.endereco_formatado = f"{address.logradouro}, {address.numero}, Lages - SC"
    address.place_id = f"demo-{address.logradouro}-{address.numero}"
    return {
        "success": True,
        "latitude": float(address.latitude),
        "longitude": float(address.longitude),
        "endereco_formatado": address.endereco_formatado,
        "place_id": address.place_id,
    }


def test_prepare_homologacao_creates_expected_scenario(monkeypatch, client):
    monkeypatch.setattr(seed_homologacao, "geocode_address", _fake_geocode)

    with SessionLocal() as db:
        result = seed_homologacao.prepare_homologacao(db)

    with SessionLocal() as db:
        organization = db.scalar(select(Organizacao).where(Organizacao.nome == "Angeloni"))
        driver = db.scalar(select(Usuario).where(Usuario.email == "motorista1@sistema.com"))
        vehicle = db.scalar(select(Veiculo).where(Veiculo.placa == "ABC1234"))
        customers = db.scalars(select(Cliente).where(Cliente.nome.in_(["Martendal", "Mezzalira", "IFSC"]))).all()
        orders = db.scalars(select(Pedido).where(Pedido.numero_pedido.like("PED-HOMOLOGACAO-%"))).all()

        assert result["organization"].id == organization.id
        assert organization.endereco_id is not None
        assert driver.organizacao_id == organization.id
        assert driver.perfil.value == "MOTORISTA"
        assert vehicle.organizacao_id == organization.id
        assert vehicle.motorista_id == driver.id
        assert {customer.nome for customer in customers} == {"Martendal", "Mezzalira", "IFSC"}
        assert len(orders) == 3
        assert all(order.status.value == "ABERTO" for order in orders)
        assert db.scalar(select(Rota.id)) is None

        expected_addresses = {
            "Martendal": ("Rua São Joaquim", "1079", "Copacabana", "88504-011"),
            "Mezzalira": ("Avenida Caldas Júnior", "192", "Santa Helena", "88504-430"),
            "IFSC": ("Rua Heitor Villa Lobos", "225", "São Francisco", "88506-400"),
        }
        for customer in customers:
            address = db.scalar(select(Endereco).where(Endereco.cliente_id == customer.id, Endereco.principal.is_(True)))
            assert address is not None
            assert (
                address.logradouro,
                address.numero,
                address.bairro,
                address.cep,
            ) == expected_addresses[customer.nome]
            assert address.latitude is not None
            assert address.longitude is not None


def test_prepare_homologacao_is_idempotent(monkeypatch, client):
    monkeypatch.setattr(seed_homologacao, "geocode_address", _fake_geocode)

    with SessionLocal() as db:
        seed_homologacao.prepare_homologacao(db)
    with SessionLocal() as db:
        seed_homologacao.prepare_homologacao(db)

    with SessionLocal() as db:
        assert db.scalar(select(Organizacao.id).where(Organizacao.nome == "Angeloni")) is not None
        assert db.scalar(select(Usuario.id).where(Usuario.email == "motorista1@sistema.com")) is not None
        assert db.scalar(select(Veiculo.id).where(Veiculo.placa == "ABC1234")) is not None
        assert db.scalar(select(Cliente.id).where(Cliente.nome == "Martendal")) is not None
        assert db.scalar(select(Cliente.id).where(Cliente.nome == "Mezzalira")) is not None
        assert db.scalar(select(Cliente.id).where(Cliente.nome == "IFSC")) is not None
        assert db.scalar(select(Pedido.id).where(Pedido.numero_pedido == "PED-HOMOLOGACAO-MARTENDAL")) is not None
        assert db.scalar(select(Pedido.id).where(Pedido.numero_pedido == "PED-HOMOLOGACAO-MEZZALIRA")) is not None
        assert db.scalar(select(Pedido.id).where(Pedido.numero_pedido == "PED-HOMOLOGACAO-IFSC")) is not None
        assert db.scalar(select(Rota.id)) is None
        assert db.scalar(select(Endereco.id).where(Endereco.cliente_id.is_not(None))) is not None

        customer_count = db.query(Cliente).filter(Cliente.nome.in_(["Martendal", "Mezzalira", "IFSC"])).count()
        order_count = db.query(Pedido).filter(Pedido.numero_pedido.like("PED-HOMOLOGACAO-%")).count()
        scenario_address_count = db.query(Endereco).filter(
            Endereco.cliente_id.in_(
                select(Cliente.id).where(Cliente.nome.in_(["Martendal", "Mezzalira", "IFSC"]))
            ),
            Endereco.principal.is_(True),
        ).count()
        assert customer_count == 3
        assert order_count == 3
        assert scenario_address_count == 3
