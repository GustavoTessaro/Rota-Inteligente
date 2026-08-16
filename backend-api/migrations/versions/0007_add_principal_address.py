"""add principal address flag to enderecos

Revision ID: 0007_add_principal_address
Revises: 0006_add_organizacao_enderecos
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_add_principal_address"
down_revision = "0006_add_organizacao_enderecos"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("enderecos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("principal", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("enderecos", schema=None) as batch_op:
        try:
            batch_op.drop_column("principal")
        except Exception:
            pass
