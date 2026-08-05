"""create rotas

Revision ID: 0004_create_rotas
Revises: 0003_create_veiculos
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_create_rotas"
down_revision = "0003_create_veiculos"
branch_labels = None
depends_on = None


status_rota = sa.Enum(
    "PLANEJADA", "AGUARDANDO_MOTORISTA", "AGUARDANDO_VEICULO", "PRONTA",
    "EM_EXECUCAO", "PAUSADA", "FINALIZADA", "CANCELADA",
    name="statusrota",
)
tipo_evento_rota = sa.Enum(
    "PARTIDA", "PAUSA", "RETOMADA", "ABASTECIMENTO", "DESVIO",
    "MANUTENCAO", "ENTREGA_REALIZADA", "ENTREGA_FALHOU", "FINALIZADA",
    name="tipoeventorota",
)


def upgrade():
    op.create_table(
        "rotas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("descricao", sa.Text()),
        sa.Column("organizacao_id", sa.Integer(), sa.ForeignKey("organizacoes.id"), nullable=False),
        sa.Column("veiculo_id", sa.Integer(), sa.ForeignKey("veiculos.id")),
        sa.Column("motorista_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("status", status_rota, nullable=False),
        sa.Column("data_planejada", sa.DateTime()),
        sa.Column("data_inicio", sa.DateTime()),
        sa.Column("data_conclusao", sa.DateTime()),
        sa.Column("origem_endereco_id", sa.Integer(), sa.ForeignKey("enderecos.id")),
        sa.Column("destino_endereco_id", sa.Integer(), sa.ForeignKey("enderecos.id")),
        sa.Column("distancia_prevista", sa.Numeric(10, 2), nullable=False),
        sa.Column("duracao_prevista", sa.Numeric(10, 2), nullable=False),
        sa.Column("distancia_real", sa.Numeric(10, 2), nullable=False),
        sa.Column("duracao_real", sa.Numeric(10, 2), nullable=False),
        sa.Column("progresso_percentual", sa.Integer(), nullable=False),
        sa.Column("quilometragem_inicial", sa.Integer()),
        sa.Column("quilometragem_final", sa.Integer()),
        sa.Column("combustivel_inicial", sa.Numeric(10, 2)),
        sa.Column("combustivel_final", sa.Numeric(10, 2)),
        sa.Column("google_route_id", sa.String(255)),
        sa.Column("google_optimization_request_id", sa.String(255)),
        sa.Column("route_geometry", sa.Text()),
        sa.Column("observacoes", sa.Text()),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rotas_organizacao_id", "rotas", ["organizacao_id"])
    op.create_index("ix_rotas_veiculo_id", "rotas", ["veiculo_id"])
    op.create_index("ix_rotas_motorista_id", "rotas", ["motorista_id"])
    op.create_index("ix_rotas_origem_endereco_id", "rotas", ["origem_endereco_id"])
    op.create_index("ix_rotas_destino_endereco_id", "rotas", ["destino_endereco_id"])

    op.create_table(
        "rota_entregas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rota_id", sa.Integer(), sa.ForeignKey("rotas.id"), nullable=False),
        sa.Column("entrega_id", sa.Integer(), sa.ForeignKey("entregas.id"), nullable=False),
        sa.Column("ordem_visita", sa.Integer(), nullable=False),
        sa.Column("sequencia_otimizada", sa.Integer()),
        sa.Column("prioridade", sa.Enum("BAIXA", "NORMAL", "ALTA", "URGENTE", name="prioridade")),
        sa.Column("janela_inicio", sa.DateTime()),
        sa.Column("janela_fim", sa.DateTime()),
        sa.Column("tempo_estacionamento", sa.Integer()),
        sa.Column("peso", sa.Numeric(10, 2)),
        sa.Column("volume", sa.Numeric(10, 2)),
    )
    op.create_index("ix_rota_entregas_rota_id", "rota_entregas", ["rota_id"])
    op.create_index("ix_rota_entregas_entrega_id", "rota_entregas", ["entrega_id"])

    op.create_table(
        "rota_historico",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rota_id", sa.Integer(), sa.ForeignKey("rotas.id"), nullable=False),
        sa.Column("evento", tipo_evento_rota, nullable=False),
        sa.Column("status_anterior", sa.String(50)),
        sa.Column("status_novo", sa.String(50), nullable=False),
        sa.Column("observacao", sa.Text()),
        sa.Column("entrega_id", sa.Integer(), sa.ForeignKey("entregas.id")),
        sa.Column("alterado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rota_historico_rota_id", "rota_historico", ["rota_id"])
    op.create_index("ix_rota_historico_entrega_id", "rota_historico", ["entrega_id"])
    op.create_index("ix_rota_historico_alterado_por", "rota_historico", ["alterado_por"])

    op.create_table(
        "rota_posicoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rota_id", sa.Integer(), sa.ForeignKey("rotas.id"), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 8), nullable=False),
        sa.Column("longitude", sa.Numeric(11, 8), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("velocidade", sa.Numeric(10, 2)),
        sa.Column("heading", sa.Numeric(6, 2)),
        sa.Column("accuracy", sa.Numeric(10, 2)),
        sa.Column("endereco", sa.Text()),
        sa.Column("provider", sa.String(50)),
        sa.Column("motorista_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("veiculo_id", sa.Integer(), sa.ForeignKey("veiculos.id")),
    )
    op.create_index("ix_rota_posicoes_rota_id", "rota_posicoes", ["rota_id"])
    op.create_index("ix_rota_posicoes_motorista_id", "rota_posicoes", ["motorista_id"])
    op.create_index("ix_rota_posicoes_veiculo_id", "rota_posicoes", ["veiculo_id"])


def downgrade():
    op.drop_index("ix_rota_posicoes_veiculo_id", table_name="rota_posicoes")
    op.drop_index("ix_rota_posicoes_motorista_id", table_name="rota_posicoes")
    op.drop_index("ix_rota_posicoes_rota_id", table_name="rota_posicoes")
    op.drop_table("rota_posicoes")

    op.drop_index("ix_rota_historico_alterado_por", table_name="rota_historico")
    op.drop_index("ix_rota_historico_entrega_id", table_name="rota_historico")
    op.drop_index("ix_rota_historico_rota_id", table_name="rota_historico")
    op.drop_table("rota_historico")

    op.drop_index("ix_rota_entregas_entrega_id", table_name="rota_entregas")
    op.drop_index("ix_rota_entregas_rota_id", table_name="rota_entregas")
    op.drop_table("rota_entregas")

    op.drop_index("ix_rotas_destino_endereco_id", table_name="rotas")
    op.drop_index("ix_rotas_origem_endereco_id", table_name="rotas")
    op.drop_index("ix_rotas_motorista_id", table_name="rotas")
    op.drop_index("ix_rotas_veiculo_id", table_name="rotas")
    op.drop_index("ix_rotas_organizacao_id", table_name="rotas")
    op.drop_table("rotas")

    tipo_evento_rota.drop(op.get_bind(), checkfirst=True)
    status_rota.drop(op.get_bind(), checkfirst=True)
