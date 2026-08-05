from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Cliente, Endereco, Entrega, HistoricoEntrega, Organizacao, Pedido, PedidoItem,
    Perfil, Prioridade, Produto, StatusEntrega, StatusVeiculo, TipoVeiculo, Usuario, Veiculo,
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

    addresses = []
    for i, client in enumerate(clients, 1):
        addresses.extend([
            Endereco(cliente_id=client.id, logradouro=f"Rua Origem {i}", numero=str(i),
                     bairro="Centro", cidade="São Paulo", estado="SP", cep="01000-000", tipo="ORIGEM"),
            Endereco(cliente_id=client.id, logradouro=f"Rua Destino {i}", numero=str(i + 100),
                     bairro="Bairro", cidade="São Paulo", estado="SP", cep="02000-000", tipo="DESTINO"),
        ])
    db.add_all(addresses)
    products = [
        Produto(nome=f"Produto {i}", descricao="Item para entrega", peso=Decimal("1.0"),
                volume=Decimal("0.5"), valor_declarado=Decimal(str(i * 10)))
        for i in range(1, 11)
    ]
    db.add_all(products)
    db.flush()

    statuses = list(StatusEntrega)
    organizations = [
        Organizacao(nome="Operação Norte", cnpj="12345678000199", email="norte@sistema.com",
                     telefone="11999990001", endereco="Av. Norte, 100"),
        Organizacao(nome="Operação Sul", cnpj="12345678000270", email="sul@sistema.com",
                     telefone="11999990002", endereco="Av. Sul, 200"),
    ]
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
        product = products[i % len(products)]
        order = Pedido(
            cliente_id=client.id, numero_pedido=f"PED-DEMO-{i + 1:03d}",
            prioridade=list(Prioridade)[i % 4], valor_total=product.valor_declarado,
            criado_por=users[1].id, forma_pagamento="A combinar",
        )
        order.itens = [PedidoItem(produto_id=product.id, quantidade=1,
                                  valor_unitario=product.valor_declarado)]
        db.add(order)
        db.flush()
        status = statuses[i % len(statuses)]
        delivery = Entrega(
            pedido_id=order.id, entregador_id=users[3 + (i % 3)].id,
            endereco_origem_id=addresses[(i % 5) * 2].id,
            endereco_destino_id=addresses[(i % 5) * 2 + 1].id,
            status=status, previsao_saida=datetime.now() - timedelta(hours=2),
            previsao_entrega=datetime.now() + timedelta(hours=(i % 7) - 3),
        )
        db.add(delivery)
        db.flush()
        db.add(HistoricoEntrega(
            entrega_id=delivery.id, status_anterior=None, status_novo=status.value,
            observacao="Carga inicial", alterado_por=users[0].id,
        ))
    db.commit()
