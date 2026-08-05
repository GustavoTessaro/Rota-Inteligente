"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


perfil = sa.Enum("ADMIN", "GESTOR", "MOTORISTA", "CLIENTE", name="perfil")
status_pedido = sa.Enum("ABERTO", "EM_PROCESSAMENTO", "FINALIZADO", "CANCELADO", name="statuspedido")
prioridade = sa.Enum("BAIXA", "NORMAL", "ALTA", "URGENTE", name="prioridade")
status_entrega = sa.Enum(
    "AGUARDANDO_COLETA", "COLETADA", "EM_ROTA", "ENTREGUE", "NAO_ENTREGUE", "CANCELADA",
    name="statusentrega",
)


def upgrade():
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("email", sa.String(150), nullable=False),
        sa.Column("senha_hash", sa.String(255), nullable=False),
        sa.Column("telefone", sa.String(20)),
        sa.Column("perfil", perfil, nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_usuarios_email", "usuarios", ["email"], unique=True)

    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("cpf_cnpj", sa.String(20), unique=True),
        sa.Column("email", sa.String(150)),
        sa.Column("telefone", sa.String(20)),
        sa.Column("observacoes", sa.Text()),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_clientes_nome", "clientes", ["nome"])

    op.create_table(
        "produtos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("descricao", sa.Text()),
        sa.Column("peso", sa.Numeric(10, 2), nullable=False),
        sa.Column("volume", sa.Numeric(10, 2), nullable=False),
        sa.Column("valor_declarado", sa.Numeric(10, 2), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "enderecos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("clientes.id"), nullable=False),
        sa.Column("logradouro", sa.String(150), nullable=False),
        sa.Column("numero", sa.String(20), nullable=False),
        sa.Column("complemento", sa.String(100)),
        sa.Column("bairro", sa.String(100), nullable=False),
        sa.Column("cidade", sa.String(100), nullable=False),
        sa.Column("estado", sa.String(2), nullable=False),
        sa.Column("cep", sa.String(10), nullable=False),
        sa.Column("referencia", sa.String(255)),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_enderecos_cliente_id", "enderecos", ["cliente_id"])

    op.create_table(
        "pedidos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("clientes.id"), nullable=False),
        sa.Column("numero_pedido", sa.String(30), nullable=False),
        sa.Column("status", status_pedido, nullable=False),
        sa.Column("prioridade", prioridade, nullable=False),
        sa.Column("forma_pagamento", sa.String(50)),
        sa.Column("valor_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("observacoes", sa.Text()),
        sa.Column("criado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_pedidos_cliente_id", "pedidos", ["cliente_id"])
    op.create_index("ix_pedidos_numero_pedido", "pedidos", ["numero_pedido"], unique=True)

    op.create_table(
        "pedido_itens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pedido_id", sa.Integer(), sa.ForeignKey("pedidos.id"), nullable=False),
        sa.Column("produto_id", sa.Integer(), sa.ForeignKey("produtos.id"), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("valor_unitario", sa.Numeric(10, 2), nullable=False),
        sa.Column("observacoes", sa.Text()),
    )
    op.create_index("ix_pedido_itens_pedido_id", "pedido_itens", ["pedido_id"])

    op.create_table(
        "entregas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pedido_id", sa.Integer(), sa.ForeignKey("pedidos.id"), nullable=False),
        sa.Column("entregador_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("endereco_origem_id", sa.Integer(), sa.ForeignKey("enderecos.id"), nullable=False),
        sa.Column("endereco_destino_id", sa.Integer(), sa.ForeignKey("enderecos.id"), nullable=False),
        sa.Column("status", status_entrega, nullable=False),
        sa.Column("previsao_saida", sa.DateTime()),
        sa.Column("previsao_entrega", sa.DateTime()),
        sa.Column("data_coleta", sa.DateTime()),
        sa.Column("data_entrega", sa.DateTime()),
        sa.Column("observacoes", sa.Text()),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_entregas_pedido_id", "entregas", ["pedido_id"])
    op.create_index("ix_entregas_entregador_id", "entregas", ["entregador_id"])
    op.create_index("ix_entregas_previsao_entrega", "entregas", ["previsao_entrega"])

    op.create_table(
        "historico_entregas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entrega_id", sa.Integer(), sa.ForeignKey("entregas.id"), nullable=False),
        sa.Column("status_anterior", sa.String(50)),
        sa.Column("status_novo", sa.String(50), nullable=False),
        sa.Column("observacao", sa.Text()),
        sa.Column("alterado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_historico_entregas_entrega_id", "historico_entregas", ["entrega_id"])

    op.create_table(
        "ocorrencias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entrega_id", sa.Integer(), sa.ForeignKey("entregas.id"), nullable=False),
        sa.Column("tipo", sa.String(100), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("registrado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ocorrencias_entrega_id", "ocorrencias", ["entrega_id"])

    op.create_table(
        "comprovantes_entrega",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entrega_id", sa.Integer(), sa.ForeignKey("entregas.id"), nullable=False),
        sa.Column("nome_recebedor", sa.String(150), nullable=False),
        sa.Column("documento_recebedor", sa.String(50), nullable=False),
        sa.Column("observacao", sa.Text()),
        sa.Column("criado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("entrega_id"),
    )
    op.create_index("ix_comprovantes_entrega_entrega_id", "comprovantes_entrega", ["entrega_id"])


def downgrade():
    op.drop_table("comprovantes_entrega")
    op.drop_table("ocorrencias")
    op.drop_table("historico_entregas")
    op.drop_table("entregas")
    op.drop_table("pedido_itens")
    op.drop_table("pedidos")
    op.drop_table("enderecos")
    op.drop_table("produtos")
    op.drop_table("clientes")
    op.drop_table("usuarios")
