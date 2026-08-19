"""add carga_confirmada to rotas

Revision ID: 0009_add_carga_confirmada_to_rotas
Revises: 0008_add_organizacao_id_to_pedidos
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_add_carga_confirmada_to_rotas"
down_revision = "0008_add_organizacao_id_to_pedidos"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "rotas",
        sa.Column("carga_confirmada", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.batch_alter_table("rotas", schema=None) as batch_op:
        batch_op.alter_column("carga_confirmada", server_default=None)


def downgrade():
    op.drop_column("rotas", "carga_confirmada")