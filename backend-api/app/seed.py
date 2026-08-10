from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Cliente, Endereco, Entrega, HistoricoEntrega, Organizacao, Pedido, PedidoItem,
    Perfil, Prioridade, Produto, StatusEntrega, StatusVeiculo, TipoVeiculo, Usuario, Veiculo,
    Rota, RotaEntrega, RotaHistorico, StatusRota, TipoEventoRota,
)
from .security import hash_password


def seed_database(db: Session) -> None:
    if db.scalar(select(Usuario.id).limit(1)):
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
    route = Rota(
        nome="Rota de Exemplo",
        descricao="Rota inicial com uma entrega de demonstração",
        organizacao_id=organizations[0].id,
        veiculo_id=vehicles[0].id,
        motorista_id=users[3].id,
        status=StatusRota.PLANEJADA,
        data_planejada=datetime.now() + timedelta(hours=1),
        origem_endereco_id=organization_addresses[0].id,
        destino_endereco_id=addresses[0].id,
        distancia_prevista=Decimal("20.0"),
        duracao_prevista=Decimal("0.75"),
        observacoes="Rota de teste",
    )
    route.entregas = [RotaEntrega(
        entrega_id=1,
        ordem_visita=1,
        sequencia_otimizada=1,
        prioridade=Prioridade.NORMAL,
        janela_inicio=datetime.now() + timedelta(hours=1),
        janela_fim=datetime.now() + timedelta(hours=3),
        tempo_estacionamento=15,
        peso=Decimal("10"),
        volume=Decimal("1"),
    )]
    route.historico = [RotaHistorico(
        evento=TipoEventoRota.PARTIDA,
        status_anterior=None,
        status_novo=StatusRota.PLANEJADA.value,
        observacao="Rota criada",
        alterado_por=users[0].id,
    )]
    db.add(route)
    db.commit()
