"""create organizacoes

Revision ID: 0002_create_organizacoes
Revises: 0001_initial_schema
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_create_organizacoes"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organizacoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("cnpj", sa.String(14), nullable=False),
        sa.Column("email", sa.String(150), nullable=False),
        sa.Column("telefone", sa.String(20)),
        sa.Column("endereco", sa.String(255), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cnpj"),
    )
    op.create_index("ix_organizacoes_nome", "organizacoes", ["nome"])
    op.create_index("ix_organizacoes_cnpj", "organizacoes", ["cnpj"], unique=True)
    op.create_index("ix_organizacoes_email", "organizacoes", ["email"])


def downgrade():
    op.drop_index("ix_organizacoes_email", table_name="organizacoes")
    op.drop_index("ix_organizacoes_cnpj", table_name="organizacoes")
    op.drop_index("ix_organizacoes_nome", table_name="organizacoes")
    op.drop_table("organizacoes")
