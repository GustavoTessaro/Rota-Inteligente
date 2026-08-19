"""make receipt document optional

Revision ID: 0010_make_receipt_document_optional
Revises: 0009_add_carga_confirmada_to_rotas
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_make_receipt_document_optional"
down_revision = "0009_add_carga_confirmada_to_rotas"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("comprovantes_entrega") as batch_op:
        batch_op.alter_column(
            "documento_recebedor",
            existing_type=sa.String(length=50),
            nullable=True,
        )


def downgrade():
    with op.batch_alter_table("comprovantes_entrega") as batch_op:
        batch_op.alter_column(
            "documento_recebedor",
            existing_type=sa.String(length=50),
            nullable=False,
        )
