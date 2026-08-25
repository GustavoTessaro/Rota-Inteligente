from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .deps import geocode_address
from .models import (
    Cliente,
    Endereco,
    Entrega,
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
    StatusVeiculo,
    TipoVeiculo,
    Usuario,
    Veiculo,
)

TRACKING_VEHICLE_PLATE = "TRKB1234"
SCENARIOS = {
    "A": {
        "organization": "Angeloni",
        "manager": "gestor1@sistema.com",
        "driver": "motorista1@sistema.com",
        "vehicle": "ABC1234",
        "customer": "TRACKING CLIENTE A",
        "order": "PED-TRACKING-A",
        "route": "Rota Homologação Tracking A",
        "address": {
            "logradouro": "Rua Tracking A",
            "numero": "101",
            "bairro": "Centro",
            "cidade": "Lages",
            "estado": "SC",
            "cep": "88500001",
        },
    },
    "B": {
        "organization": "Operação Sul",
        "manager": "gestor2@sistema.com",
        "driver": "motorista3@sistema.com",
        "vehicle": TRACKING_VEHICLE_PLATE,
        "customer": "TRACKING CLIENTE B",
        "order": "PED-TRACKING-B",
        "route": "Rota Homologação Tracking B",
        "address": {
            "logradouro": "Rua Tracking B",
            "numero": "202",
            "bairro": "Universitário",
            "cidade": "Lages",
            "estado": "SC",
            "cep": "88500002",
        },
    },
}

PROTECTED_ROUTE_STATUSES = {
    StatusRota.RASCUNHO,
    StatusRota.OTIMIZANDO,
    StatusRota.PLANEJADA,
    StatusRota.AGUARDANDO_ACEITE,
    StatusRota.AGUARDANDO_MOTORISTA,
    StatusRota.AGUARDANDO_VEICULO,
    StatusRota.PRONTA,
    StatusRota.EM_EXECUCAO,
    StatusRota.PAUSADA,
}
TERMINAL_ROUTE_STATUSES = {StatusRota.FINALIZADA, StatusRota.CANCELADA, StatusRota.CONCLUIDA}


def _find_required(db: Session, model, value, field: str):
    item = db.scalar(select(model).where(getattr(model, field) == value))
    if item is None:
        raise RuntimeError(f"Registro obrigatório não encontrado: {model.__name__}.{field}={value}")
    return item


def _ensure_tracking_vehicle(db: Session, organization: Organizacao, driver: Usuario) -> Veiculo:
    vehicle = db.scalar(select(Veiculo).where(Veiculo.placa == TRACKING_VEHICLE_PLATE))
    if vehicle is None:
        vehicle = Veiculo(
            placa=TRACKING_VEHICLE_PLATE,
            modelo="Ducato Tracking",
            marca="Fiat",
            ano=2024,
            cor="Branco",
            capacidade_carga=Decimal("1200"),
            capacidade_volume=Decimal("12"),
            tipo=TipoVeiculo.VAN,
            status=StatusVeiculo.DISPONIVEL,
            ativo=True,
            organizacao_id=organization.id,
            motorista_id=driver.id,
        )
        db.add(vehicle)
        db.flush()
    elif vehicle.organizacao_id != organization.id or vehicle.motorista_id != driver.id:
        raise RuntimeError(f"Veículo {TRACKING_VEHICLE_PLATE} já existe com vínculo incompatível")
    return vehicle


def _ensure_customer_address(db: Session, scenario: dict) -> tuple[Cliente, Endereco]:
    customer = db.scalar(select(Cliente).where(Cliente.nome == scenario["customer"]))
    if customer is None:
        customer = Cliente(nome=scenario["customer"], ativo=True)
        db.add(customer)
        db.flush()

    address_values = scenario["address"]
    address = db.scalar(
        select(Endereco).where(
            Endereco.cliente_id == customer.id,
            Endereco.logradouro == address_values["logradouro"],
            Endereco.numero == address_values["numero"],
        )
    )
    if address is None:
        address = Endereco(
            **address_values,
            cliente_id=customer.id,
            tipo="DESTINO",
            principal=True,
        )
        db.add(address)
        db.flush()
    if address.latitude is None or address.longitude is None:
        result = geocode_address(db, address)
        if not result.get("success"):
            raise RuntimeError(f"Falha ao geocodificar {scenario['customer']}: {result.get('error')}")
    return customer, address


def _next_route_index(db: Session, base_name: str) -> int:
    routes = db.scalars(select(Rota).where(Rota.nome == base_name)).all()
    index = 1
    while True:
        candidate = base_name if index == 1 else f"{base_name} #{index}"
        if not any(route.nome == candidate for route in routes):
            return index
        index += 1


def _find_reusable_or_protected_route(db: Session, base_name: str) -> tuple[Rota | None, bool]:
    routes = db.scalars(select(Rota).where(Rota.nome.like(f"{base_name}%")).order_by(Rota.id)).all()
    for route in routes:
        if route.status == StatusRota.PRONTA:
            return route, False
    for route in routes:
        if route.status in PROTECTED_ROUTE_STATUSES:
            return route, True
    return None, False


def _ensure_scenario(db: Session, key: str, scenario: dict, product: Produto, creator: Usuario) -> dict[str, object]:
    organization = _find_required(db, Organizacao, scenario["organization"], "nome")
    manager = _find_required(db, Usuario, scenario["manager"], "email")
    driver = _find_required(db, Usuario, scenario["driver"], "email")
    if manager.organizacao_id != organization.id or driver.organizacao_id != organization.id:
        raise RuntimeError(f"Usuários do cenário {key} não pertencem à organização esperada")
    vehicle = _find_required(db, Veiculo, scenario["vehicle"], "placa") if key == "A" else _ensure_tracking_vehicle(db, organization, driver)
    if vehicle.organizacao_id != organization.id or vehicle.motorista_id != driver.id:
        raise RuntimeError(f"Veículo do cenário {key} não possui vínculo esperado")

    base_route_name = scenario["route"]
    existing_route, protected = _find_reusable_or_protected_route(db, base_route_name)
    if existing_route is not None:
        return {"organization": organization, "manager": manager, "driver": driver, "vehicle": vehicle, "route": existing_route, "protected": protected}

    customer, address = _ensure_customer_address(db, scenario)
    route_index = _next_route_index(db, base_route_name)
    order_number = scenario["order"] if route_index == 1 else f"{scenario['order']}-{route_index}"
    order = db.scalar(select(Pedido).where(Pedido.numero_pedido == order_number))
    if order is None:
        order = Pedido(
            cliente_id=customer.id,
            organizacao_id=organization.id,
            endereco_entrega_id=address.id,
            numero_pedido=order_number,
            status=StatusPedido.ABERTO,
            criado_por=creator.id,
        )
        order.itens = [PedidoItem(produto_id=product.id, quantidade=1, valor_unitario=product.valor_declarado)]
        db.add(order)
        db.flush()

    delivery = db.scalar(select(Entrega).where(Entrega.pedido_id == order.id).order_by(Entrega.id))
    if delivery is None:
        delivery = Entrega(
            pedido_id=order.id,
            entregador_id=driver.id,
            endereco_origem_id=organization.endereco_id,
            endereco_destino_id=address.id,
            status=StatusEntrega.AGUARDANDO_COLETA,
        )
        db.add(delivery)
        db.flush()
    elif delivery.status != StatusEntrega.AGUARDANDO_COLETA:
        raise RuntimeError(f"Entrega tracking {delivery.id} não está planejável: {delivery.status.value}")

    route_name = base_route_name if route_index == 1 else f"{base_route_name} #{route_index}"
    route = Rota(
        nome=route_name,
        descricao=f"Cenário exclusivo de homologação do tracking {key}",
        organizacao_id=organization.id,
        motorista_id=driver.id,
        veiculo_id=vehicle.id,
        status=StatusRota.PRONTA,
        carga_confirmada=False,
        origem_endereco_id=organization.endereco_id,
        destino_endereco_id=address.id,
        progresso_percentual=0,
    )
    route.entregas = [RotaEntrega(entrega_id=delivery.id, ordem_visita=1, sequencia_otimizada=1)]
    db.add(route)
    db.flush()
    return {"organization": organization, "manager": manager, "driver": driver, "vehicle": vehicle, "route": route, "protected": False}


def prepare_tracking_homologacao(db: Session) -> dict[str, object]:
    """Prepara cenários A/B sem iniciar rotas ou criar posições."""
    organization_a = _find_required(db, Organizacao, SCENARIOS["A"]["organization"], "nome")
    organization_b = _find_required(db, Organizacao, SCENARIOS["B"]["organization"], "nome")
    creator = _find_required(db, Usuario, "admin@sistema.com", "email")
    product = db.scalar(select(Produto).where(Produto.ativo.is_(True)).order_by(Produto.id))
    if product is None:
        raise RuntimeError("É necessário possuir pelo menos um produto ativo")

    result = {
        "organization_a": organization_a,
        "organization_b": organization_b,
        "routes": {},
        "protected": {},
    }
    for key, scenario in SCENARIOS.items():
        prepared = _ensure_scenario(db, key, scenario, product, creator)
        result["routes"][key] = prepared["route"]
        if prepared["protected"]:
            result["protected"][key] = prepared["route"]
    db.commit()
    return result


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        result = prepare_tracking_homologacao(db)
        for key in ("A", "B"):
            route = result["routes"][key]
            print(f"Cenário {key}: rota {route.id} - {route.nome} - {route.status.value}")
        print("Posições GPS criadas: 0")


if __name__ == "__main__":
    main()
