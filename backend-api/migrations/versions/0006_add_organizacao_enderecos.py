"""add organization address support while keeping legacy organization address fields

Revision ID: 0006_add_organizacao_enderecos
Revises: 0005_add_address_geolocation
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_add_organizacao_enderecos"
down_revision = "0005_add_address_geolocation"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("enderecos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("organizacao_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_enderecos_organizacao_id", ["organizacao_id"])
        batch_op.create_foreign_key(
            "fk_enderecos_organizacao_id_organizacoes",
            "organizacoes",
            ["organizacao_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("enderecos", schema=None) as batch_op:
        batch_op.alter_column("cliente_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table("enderecos", schema=None) as batch_op:
        try:
            batch_op.drop_constraint("fk_enderecos_organizacao_id_organizacoes", type_="foreignkey")
        except Exception:
            pass
        try:
            batch_op.drop_index("ix_enderecos_organizacao_id")
        except Exception:
            pass
        try:
            batch_op.drop_column("organizacao_id")
        except Exception:
            pass

    with op.batch_alter_table("enderecos", schema=None) as batch_op:
        batch_op.alter_column("cliente_id", existing_type=sa.Integer(), nullable=False)
