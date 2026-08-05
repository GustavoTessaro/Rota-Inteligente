"""create veiculos

Revision ID: 0003_create_veiculos
Revises: 0002_create_organizacoes
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_create_veiculos"
down_revision = "0002_create_organizacoes"
branch_labels = None
depends_on = None


tipo_veiculo = sa.Enum(
    "CARRO", "VAN", "UTILITARIO", "CAMINHAO", "CARRETA", "OUTRO",
    name="tipoveiculo",
)
status_veiculo = sa.Enum(
    "DISPONIVEL", "EM_ROTTA", "MANUTENCAO",
    name="statusveiculo",
)


def upgrade():
    op.create_table(
        "veiculos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organizacao_id", sa.Integer(), sa.ForeignKey("organizacoes.id"), nullable=False),
        sa.Column("motorista_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("placa", sa.String(10), nullable=False),
        sa.Column("modelo", sa.String(150), nullable=False),
        sa.Column("marca", sa.String(150), nullable=False),
        sa.Column("ano", sa.Integer(), nullable=False),
        sa.Column("cor", sa.String(50), nullable=False),
        sa.Column("capacidade_carga", sa.Numeric(10, 2), nullable=False),
        sa.Column("capacidade_volume", sa.Numeric(10, 2), nullable=False),
        sa.Column("tipo", tipo_veiculo, nullable=False),
        sa.Column("status", status_veiculo, nullable=False),
        sa.Column("quilometragem", sa.Integer(), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_veiculos_organizacao_id", "veiculos", ["organizacao_id"])
    op.create_index("ix_veiculos_motorista_id", "veiculos", ["motorista_id"])
    op.create_index("ix_veiculos_placa", "veiculos", ["placa"], unique=True)


def downgrade():
    op.drop_index("ix_veiculos_placa", table_name="veiculos")
    op.drop_index("ix_veiculos_motorista_id", table_name="veiculos")
    op.drop_index("ix_veiculos_organizacao_id", table_name="veiculos")
    op.drop_table("veiculos")
    status_veiculo.drop(op.get_bind(), checkfirst=True)
    tipo_veiculo.drop(op.get_bind(), checkfirst=True)
