"""add organization link to users

Revision ID: 0011_add_organizacao_id_to_usuarios
Revises: 0010_make_receipt_document_optional
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_add_organizacao_id_to_usuarios"
down_revision = "0010_make_receipt_document_optional"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.add_column(sa.Column("organizacao_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_usuarios_organizacao_id", ["organizacao_id"])
        batch_op.create_foreign_key(
            "fk_usuarios_organizacao_id_organizacoes",
            "organizacoes",
            ["organizacao_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.drop_constraint("fk_usuarios_organizacao_id_organizacoes", type_="foreignkey")
        batch_op.drop_index("ix_usuarios_organizacao_id")
        batch_op.drop_column("organizacao_id")
