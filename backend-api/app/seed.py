from datetime import datetime, timedelta
from decimal import Decimal
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Cliente, Endereco, Entrega, HistoricoEntrega, Organizacao, Pedido, PedidoItem,
    CriterioAlternativaRota, Perfil, Prioridade, Produto, StatusEntrega, StatusVeiculo,
    TipoVeiculo, Usuario, Veiculo, Rota, RotaAlternativa, RotaEntrega, RotaHistorico,
    StatusRota, TipoEventoRota,
)
from .security import hash_password


DEMO_ROUTE_NAMES = (
    "Rota Demonstração - Escolha Rápida",
    "Rota Demonstração - Escolha Curta",
)


def _ensure_demo_route(
    db: Session,
    *,
    name: str,
    organization: Organizacao,
    driver: Usuario,
    vehicle: Veiculo,
    deliveries: list[Entrega],
    recommended_criterion: CriterioAlternativaRota,
    selected_criterion: CriterioAlternativaRota,
    distance_fast: str,
    duration_fast: str,
    distance_short: str,
    duration_short: str,
) -> Rota:
    route = db.scalar(select(Rota).where(Rota.nome == name))
    if route is None:
        route = Rota(
            nome=name,
            descricao="Rota demonstrativa do fluxo de alternativas",
            organizacao_id=organization.id,
            veiculo_id=vehicle.id,
            motorista_id=driver.id,
            status=StatusRota.PRONTA,
            data_planejada=datetime.now(),
            origem_endereco_id=organization.endereco_id,
            destino_endereco_id=deliveries[-1].endereco_destino_id,
            distancia_prevista=Decimal(distance_fast),
            duracao_prevista=Decimal(duration_fast),
            progresso_percentual=0,
        )
        db.add(route)
        db.flush()

    existing_delivery_ids = {entry.entrega_id for entry in route.entregas}
    for order, delivery in enumerate(deliveries, start=1):
        if delivery.id not in existing_delivery_ids:
            db.add(RotaEntrega(rota=route, entrega_id=delivery.id, ordem_visita=order, sequencia_otimizada=order))
    db.flush()

    alternative_data = {
        CriterioAlternativaRota.MAIS_RAPIDA: (distance_fast, duration_fast),
        CriterioAlternativaRota.MAIS_CURTA: (distance_short, duration_short),
    }
    alternatives = {}
    for criterion, (distance, duration) in alternative_data.items():
        alternative = db.scalar(
            select(RotaAlternativa).where(
                RotaAlternativa.rota_id == route.id,
                RotaAlternativa.criterio == criterion,
            )
        )
        if alternative is None:
            alternative = RotaAlternativa(
                rota_id=route.id,
                criterio=criterion,
                distancia_prevista=Decimal(distance),
                duracao_prevista=Decimal(duration),
                sequencia_json=json.dumps([delivery.id for delivery in deliveries]),
            )
            db.add(alternative)
            db.flush()
        alternatives[criterion] = alternative

    recommended = alternatives[recommended_criterion]
    selected = alternatives[selected_criterion]
    route.alternativa_recomendada_id = recommended.id
    route.alternativa_escolhida_id = selected.id
    route.alternativa_escolhida_por = driver.id
    route.alternativa_escolhida_em = datetime.now()
    route.status = StatusRota.PRONTA

    recommended_history_exists = db.scalar(
        select(RotaHistorico.id).where(
            RotaHistorico.rota_id == route.id,
            RotaHistorico.evento == TipoEventoRota.ALTERNATIVA_RECOMENDADA,
        )
    )
    selected_history_exists = db.scalar(
        select(RotaHistorico.id).where(
            RotaHistorico.rota_id == route.id,
            RotaHistorico.evento == TipoEventoRota.ALTERNATIVA_SELECIONADA,
        )
    )
    if recommended_history_exists is None:
        db.add(RotaHistorico(
            rota_id=route.id,
            evento=TipoEventoRota.ALTERNATIVA_RECOMENDADA,
            status_novo=StatusRota.PRONTA.value,
            observacao=f"Alternativa {recommended.criterio.value} recomendada",
            alterado_por=driver.id,
        ))
    if selected_history_exists is None:
        db.add(RotaHistorico(
            rota_id=route.id,
            evento=TipoEventoRota.ALTERNATIVA_SELECIONADA,
            status_novo=StatusRota.PRONTA.value,
            observacao=f"Alternativa {selected.criterio.value} selecionada",
            alterado_por=driver.id,
        ))
    return route


def _ensure_demo_routes(db: Session) -> None:
    organization = db.scalar(select(Organizacao).order_by(Organizacao.id))
    driver = db.scalar(select(Usuario).where(Usuario.email == "motorista1@sistema.com"))
    vehicle = db.scalar(select(Veiculo).where(Veiculo.placa == "ABC1234"))
    deliveries = db.scalars(
        select(Entrega)
        .where(Entrega.status == StatusEntrega.AGUARDANDO_COLETA)
        .order_by(Entrega.id)
        .limit(3)
    ).all()
    if organization is None or driver is None or vehicle is None or len(deliveries) < 3:
        return

    _ensure_demo_route(
        db,
        name=DEMO_ROUTE_NAMES[0],
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        deliveries=deliveries[:2],
        recommended_criterion=CriterioAlternativaRota.MAIS_RAPIDA,
        selected_criterion=CriterioAlternativaRota.MAIS_RAPIDA,
        distance_fast="12.40",
        duration_fast="0.80",
        distance_short="10.70",
        duration_short="1.10",
    )
    _ensure_demo_route(
        db,
        name=DEMO_ROUTE_NAMES[1],
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        deliveries=deliveries[2:],
        recommended_criterion=CriterioAlternativaRota.MAIS_RAPIDA,
        selected_criterion=CriterioAlternativaRota.MAIS_CURTA,
        distance_fast="8.60",
        duration_fast="0.60",
        distance_short="7.90",
        duration_short="0.90",
    )
    db.commit()


def seed_database(db: Session) -> None:
    if db.scalar(select(Usuario.id).limit(1)):
        _ensure_demo_routes(db)
        return

    users = [
        Usuario(nome="Administrador do Sistema", email="admin@sistema.com",
                senha_hash=hash_password("123456"), perfil=Perfil.ADMIN),
        Usuario(nome="Gestor Um", email="gestor1@sistema.com",
                senha_hash=hash_password("123456"), perfil=Perfil.GESTOR),
        Usuario(nome="Gestor Dois", email="gestor2@sistema.com",
                senha_hash=hash_password("123456"), perfil=Perfil.GESTOR),
    ]
    users += [
        Usuario(nome=f"Motorista {i}", email=f"motorista{i}@sistema.com",
                senha_hash=hash_password("123456"), perfil=Perfil.MOTORISTA)
        for i in range(1, 4)
    ]
    db.add_all(users)
    db.flush()

    clients = [
        Cliente(nome=f"Cliente {i}", cpf_cnpj=f"0000000000{i}", email=f"cliente{i}@email.com",
                telefone=f"1199999000{i}")
        for i in range(1, 6)
    ]
    db.add_all(clients)
    db.flush()

    # Endereços por cliente: todos válidos e coerentes na tabela de endereços,
    # com os pedidos apontando para um desses registros.
    addresses = []
    address_by_client: dict[int, list[Endereco]] = {}
    for i, client in enumerate(clients, 1):
        client_addresses = [
            Endereco(
                cliente_id=client.id,
                logradouro=f"Rua Origem {i}",
                numero=str(i),
                bairro="Centro",
                cidade="São Paulo",
                estado="SP",
                cep="01000-000",
                tipo="ORIGEM",
            ),
            Endereco(
                cliente_id=client.id,
                logradouro=f"Rua Destino {i}",
                numero=str(i + 100),
                bairro="Bairro",
                cidade="São Paulo",
                estado="SP",
                cep="02000-000",
                tipo="DESTINO",
            ),
        ]
        addresses.extend(client_addresses)
        address_by_client[client.id] = client_addresses
    db.add_all(addresses)
    db.flush()

    products = [
        Produto(nome=f"Produto {i}", descricao="Item para entrega", peso=Decimal("1.0"),
                volume=Decimal("0.5"), valor_declarado=Decimal(str(i * 10)))
        for i in range(1, 11)
    ]
    db.add_all(products)
    db.flush()

    statuses = list(StatusEntrega)

    # Organizations as collection points. Each organization receives a valid address
    # from the same shared Enderecos table.
    organizations = []
    organization_addresses = []
    for index, org_name in enumerate(["Operação Norte", "Operação Sul"], start=1):
        org_client = clients[(index - 1) % len(clients)]
        org_address = Endereco(
            cliente_id=org_client.id,
            logradouro=f"Av. {org_name.split()[-1]}",
            numero=str(100 + index),
            bairro="Centro",
            cidade="São Paulo",
            estado="SP",
            cep="01000-000",
            tipo="ORIGEM",
        )
        organization_addresses.append(org_address)
        organizations.append(
            Organizacao(
                nome=org_name,
                cnpj="12345678000199" if index == 1 else "12345678000270",
                email=f"{'norte' if index == 1 else 'sul'}@sistema.com",
                telefone=f"1199999000{index}",
                endereco=f"{'Av. Norte, 100' if index == 1 else 'Av. Sul, 200'}",
            )
        )
    db.add_all(organization_addresses)
    db.flush()
    for org, org_address in zip(organizations, organization_addresses, strict=True):
        org.endereco_id = org_address.id
    db.add_all(organizations)
    db.flush()

    users[1].organizacao_id = organizations[0].id
    users[2].organizacao_id = organizations[1].id
    users[3].organizacao_id = organizations[0].id
    users[4].organizacao_id = organizations[0].id
    users[5].organizacao_id = organizations[1].id

    vehicles = [
        Veiculo(placa="ABC1234", modelo="Fiat Ducato", marca="Fiat", ano=2020, cor="Branco",
                capacidade_carga=Decimal("1200"), capacidade_volume=Decimal("12"), tipo=TipoVeiculo.VAN,
                status=StatusVeiculo.DISPONIVEL, quilometragem=50000, ativo=True,
                organizacao_id=organizations[0].id, motorista_id=users[3].id),
        Veiculo(placa="XYZ9876", modelo="Mercedes-Benz Actros", marca="Mercedes", ano=2022, cor="Cinza",
                capacidade_carga=Decimal("8000"), capacidade_volume=Decimal("34"), tipo=TipoVeiculo.CAMINHAO,
                status=StatusVeiculo.MANUTENCAO, quilometragem=120000, ativo=True,
                organizacao_id=organizations[1].id, motorista_id=users[5].id),
    ]
    db.add_all(vehicles)
    db.flush()

    for i in range(15):
        client = clients[i % len(clients)]
        client_delivery_addresses = address_by_client[client.id]
        delivery_address = client_delivery_addresses[(i % len(client_delivery_addresses))]
        product = products[i % len(products)]
        order = Pedido(
            cliente_id=client.id,
            endereco_entrega_id=delivery_address.id,
            numero_pedido=f"PED-DEMO-{i + 1:03d}",
            prioridade=list(Prioridade)[i % 4],
            valor_total=product.valor_declarado,
            criado_por=users[1].id,
            forma_pagamento="A combinar",
        )
        order.itens = [PedidoItem(produto_id=product.id, quantidade=1,
                                  valor_unitario=product.valor_declarado)]
        db.add(order)
        db.flush()
        status = statuses[i % len(statuses)]
        delivery = Entrega(
            pedido_id=order.id,
            entregador_id=users[3 + (i % 3)].id,
            endereco_origem_id=address_by_client[client.id][0].id,
            endereco_destino_id=delivery_address.id,
            status=status,
            previsao_saida=datetime.now() - timedelta(hours=2),
            previsao_entrega=datetime.now() + timedelta(hours=(i % 7) - 3),
        )
        db.add(delivery)
        db.flush()
        db.add(HistoricoEntrega(
            entrega_id=delivery.id,
            status_anterior=None,
            status_novo=status.value,
            observacao="Carga inicial",
            alterado_por=users[0].id,
        ))
    db.flush()
    db.commit()
    _ensure_demo_routes(db)
