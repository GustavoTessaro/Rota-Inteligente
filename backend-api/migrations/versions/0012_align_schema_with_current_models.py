"""align schema with current models

Revision ID: 0012_align_schema_with_current_models
Revises: 0011_add_organizacao_id_to_usuarios
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_align_schema_with_current_models"
down_revision = "0011_add_organizacao_id_to_usuarios"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pedidos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("endereco_entrega_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_pedidos_endereco_entrega_id", ["endereco_entrega_id"])
        batch_op.create_foreign_key(
            "fk_pedidos_endereco_entrega_id_enderecos",
            "enderecos",
            ["endereco_entrega_id"],
            ["id"],
        )

    with op.batch_alter_table("rotas", schema=None) as batch_op:
        batch_op.create_index("ix_rotas_nome", ["nome"])

    with op.batch_alter_table("rota_historico", schema=None) as batch_op:
        batch_op.alter_column(
            "status_novo",
            existing_type=sa.String(length=50),
            nullable=True,
        )


def downgrade():
    with op.batch_alter_table("rota_historico", schema=None) as batch_op:
        batch_op.alter_column(
            "status_novo",
            existing_type=sa.String(length=50),
            nullable=False,
        )

    with op.batch_alter_table("rotas", schema=None) as batch_op:
        batch_op.drop_index("ix_rotas_nome")

    with op.batch_alter_table("pedidos", schema=None) as batch_op:
        batch_op.drop_constraint("fk_pedidos_endereco_entrega_id_enderecos", type_="foreignkey")
        batch_op.drop_index("ix_pedidos_endereco_entrega_id")
        batch_op.drop_column("endereco_entrega_id")
