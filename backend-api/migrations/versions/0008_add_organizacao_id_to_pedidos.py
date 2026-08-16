"""add organizacao_id to pedidos for route origin tracking

Revision ID: 0008_add_organizacao_id_to_pedidos
Revises: 0007_add_principal_address
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_add_organizacao_id_to_pedidos"
down_revision = "0007_add_principal_address"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pedidos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("organizacao_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_pedidos_organizacao_id", ["organizacao_id"])
        batch_op.create_foreign_key(
            "fk_pedidos_organizacao_id_organizacoes",
            "organizacoes",
            ["organizacao_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("pedidos", schema=None) as batch_op:
        try:
            batch_op.drop_constraint("fk_pedidos_organizacao_id_organizacoes", type_="foreignkey")
        except Exception:
            pass
        try:
            batch_op.drop_index("ix_pedidos_organizacao_id")
        except Exception:
            pass
        try:
            batch_op.drop_column("organizacao_id")
        except Exception:
            pass
