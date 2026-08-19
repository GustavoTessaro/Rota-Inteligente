from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .deps import geocode_address
from .models import (
    Cliente,
    Endereco,
    Organizacao,
    Pedido,
    PedidoItem,
    Perfil,
    Prioridade,
    Produto,
    StatusPedido,
    StatusVeiculo,
    TipoVeiculo,
    Usuario,
    Veiculo,
)
from .seed import seed_database
from .security import hash_password

ORGANIZATION_NAME = "Angeloni"
ORGANIZATION_CNPJ = "12345678000351"
DRIVER_EMAIL = "motorista1@sistema.com"
DEFAULT_VEHICLE_PLATE = "ABC1234"

CUSTOMER_SCENARIO = {
    "Martendal": {
        "logradouro": "Rua São Joaquim",
        "numero": "1079",
        "complemento": "Mercado",
        "bairro": "Copacabana",
        "cidade": "Lages",
        "estado": "SC",
        "cep": "88504-011",
    },
    "Mezzalira": {
        "logradouro": "Avenida Caldas Júnior",
        "numero": "192",
        "complemento": "Mercado",
        "bairro": "Santa Helena",
        "cidade": "Lages",
        "estado": "SC",
        "cep": "88504-430",
    },
    "IFSC": {
        "logradouro": "Rua Heitor Villa Lobos",
        "numero": "225",
        "complemento": "Faculdade",
        "bairro": "São Francisco",
        "cidade": "Lages",
        "estado": "SC",
        "cep": "88506-400",
    },
}

ORGANIZATION_ADDRESS = {
    "logradouro": "Rua Frei Rogério",
    "numero": "587",
    "complemento": "Mercado",
    "bairro": "Centro",
    "cidade": "Lages",
    "estado": "SC",
    "cep": "88502-161",
}


def _address_matches(address: Endereco, values: dict[str, str]) -> bool:
    return all(getattr(address, key) == value for key, value in values.items())


def _geocode_if_needed(db: Session, address: Endereco) -> None:
    if address.latitude is not None and address.longitude is not None:
        return
    result = geocode_address(db, address)
    if not result["success"]:
        raise RuntimeError(f"Falha ao geocodificar {address.logradouro}, {address.numero}: {result['error']}")


def _ensure_address(
    db: Session,
    values: dict[str, str],
    *,
    cliente_id: int | None = None,
    organizacao_id: int | None = None,
    tipo: str = "DESTINO",
    principal: bool = False,
) -> Endereco:
    addresses = db.scalars(
        select(Endereco).where(
            Endereco.cliente_id == cliente_id,
            Endereco.organizacao_id == organizacao_id,
        )
    ).all()
    address = next((item for item in addresses if _address_matches(item, values)), None)
    if address is None:
        address = Endereco(
            **values,
            cliente_id=cliente_id,
            organizacao_id=organizacao_id,
            tipo=tipo,
            principal=principal,
        )
        db.add(address)
        db.flush()
    else:
        address.tipo = tipo
        address.principal = principal
    _geocode_if_needed(db, address)
    return address


def _ensure_organization(db: Session) -> tuple[Organizacao, Endereco]:
    organization = db.scalar(select(Organizacao).where(Organizacao.nome == ORGANIZATION_NAME))
    if organization is None:
        organization = db.scalar(select(Organizacao).where(Organizacao.cnpj == ORGANIZATION_CNPJ))
    if organization is None:
        organization = Organizacao(
            nome=ORGANIZATION_NAME,
            cnpj=ORGANIZATION_CNPJ,
            email="angeloni@sistema.com",
            telefone="49999990000",
            endereco="Rua Frei Rogério, 587 - Centro, Lages/SC",
            ativo=True,
        )
        db.add(organization)
        db.flush()
    else:
        organization.nome = ORGANIZATION_NAME
        organization.ativo = True
        organization.endereco = "Rua Frei Rogério, 587 - Centro, Lages/SC"

    address = None
    if organization.endereco_id is not None:
        address = db.get(Endereco, organization.endereco_id)
        if address is not None and not _address_matches(address, ORGANIZATION_ADDRESS):
            address = None
    if address is None:
        address = _ensure_address(
            db,
            ORGANIZATION_ADDRESS,
            organizacao_id=organization.id,
            tipo="ORIGEM",
            principal=True,
        )
        organization.endereco_id = address.id
    else:
        address.organizacao_id = organization.id
        address.principal = True
    _geocode_if_needed(db, address)
    db.flush()
    return organization, address


def _ensure_driver(db: Session, organization: Organizacao) -> Usuario:
    driver = db.scalar(select(Usuario).where(Usuario.email == DRIVER_EMAIL))
    if driver is None:
        driver = Usuario(
            nome="Motorista 1",
            email=DRIVER_EMAIL,
            senha_hash=hash_password("123456"),
            perfil=Perfil.MOTORISTA,
            ativo=True,
        )
        db.add(driver)
        db.flush()
    driver.perfil = Perfil.MOTORISTA
    driver.ativo = True
    driver.organizacao_id = organization.id
    return driver


def _ensure_vehicle(db: Session, organization: Organizacao, driver: Usuario) -> Veiculo:
    vehicle = db.scalar(select(Veiculo).where(Veiculo.placa == DEFAULT_VEHICLE_PLATE))
    if vehicle is None:
        vehicle = db.scalar(select(Veiculo).order_by(Veiculo.id))
    if vehicle is None:
        vehicle = Veiculo(
            placa=DEFAULT_VEHICLE_PLATE,
            modelo="Fiat Ducato",
            marca="Fiat",
            ano=2020,
            cor="Branco",
            capacidade_carga=Decimal("1200"),
            capacidade_volume=Decimal("12"),
            tipo=TipoVeiculo.VAN,
            quilometragem=0,
        )
        db.add(vehicle)
        db.flush()
    vehicle.organizacao_id = organization.id
    vehicle.motorista_id = driver.id
    vehicle.ativo = True
    vehicle.status = StatusVeiculo.DISPONIVEL
    return vehicle


def _ensure_customer(db: Session, name: str, address_values: dict[str, str]) -> tuple[Cliente, Endereco]:
    customer = db.scalar(select(Cliente).where(Cliente.nome == name))
    if customer is None:
        customer = Cliente(nome=name, ativo=True)
        db.add(customer)
        db.flush()
    customer.ativo = True
    address = _ensure_address(db, address_values, cliente_id=customer.id, tipo="DESTINO", principal=True)
    return customer, address


def _ensure_order(
    db: Session,
    customer: Cliente,
    address: Endereco,
    organization: Organizacao,
    creator: Usuario,
    product: Produto,
    key: str,
) -> Pedido:
    order_number = f"PED-HOMOLOGACAO-{key.upper()}"
    order = db.scalar(select(Pedido).where(Pedido.numero_pedido == order_number))
    if order is None:
        order = Pedido(
            cliente_id=customer.id,
            organizacao_id=organization.id,
            endereco_entrega_id=address.id,
            numero_pedido=order_number,
            status=StatusPedido.ABERTO,
            prioridade=Prioridade.NORMAL,
            forma_pagamento="A combinar",
            valor_total=product.valor_declarado,
            criado_por=creator.id,
        )
        order.itens = [PedidoItem(produto_id=product.id, quantidade=1, valor_unitario=product.valor_declarado)]
        db.add(order)
        db.flush()
    elif not db.scalar(select(PedidoItem.id).where(PedidoItem.pedido_id == order.id)):
        order.itens = [PedidoItem(produto_id=product.id, quantidade=1, valor_unitario=product.valor_declarado)]
    order.cliente_id = customer.id
    order.organizacao_id = organization.id
    order.endereco_entrega_id = address.id
    return order


def prepare_homologacao(db: Session) -> dict[str, object]:
    """Prepare the repeatable driver-route homologation data set."""
    if not db.scalar(select(Usuario.id).limit(1)):
        seed_database(db)

    organization, organization_address = _ensure_organization(db)
    driver = _ensure_driver(db, organization)
    vehicle = _ensure_vehicle(db, organization, driver)
    creator = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.ADMIN).order_by(Usuario.id))
    product = db.scalar(select(Produto).where(Produto.ativo.is_(True)).order_by(Produto.id))
    if creator is None or product is None:
        raise RuntimeError("Seed normal precisa criar um administrador e pelo menos um produto")

    orders = []
    for name, values in CUSTOMER_SCENARIO.items():
        customer, address = _ensure_customer(db, name, values)
        orders.append(_ensure_order(db, customer, address, organization, creator, product, name))

    db.commit()
    return {
        "organization": organization,
        "organization_address": organization_address,
        "driver": driver,
        "vehicle": vehicle,
        "orders": orders,
    }


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        result = prepare_homologacao(db)
        print(f"Organização: {result['organization'].nome}")
        print(f"Motorista: {result['driver'].email}")
        print(f"Veículo: {result['vehicle'].placa}")
        print("Pedidos: " + ", ".join(order.numero_pedido for order in result["orders"]))
        print("Rotas criadas: 0")


if __name__ == "__main__":
    main()
