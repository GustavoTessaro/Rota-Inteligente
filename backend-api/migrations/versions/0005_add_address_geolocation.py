"""add address geolocation fields and organizacao endereco_id

Revision ID: 0005_add_address_geolocation
Revises: 0004_create_rotas
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_add_address_geolocation"
down_revision = "0004_create_rotas"
branch_labels = None
depends_on = None


def upgrade():
    # Add geolocation and formatted address columns to enderecos
    op.add_column("enderecos", sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("enderecos", sa.Column("longitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("enderecos", sa.Column("pais", sa.String(100), nullable=True))
    op.add_column("enderecos", sa.Column("endereco_formatado", sa.Text(), nullable=True))
    op.add_column("enderecos", sa.Column("place_id", sa.String(255), nullable=True))

    # Create indexes for commonly queried address fields if they don't exist
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_enderecos_indexes = {idx["name"] for idx in inspector.get_indexes("enderecos")} if inspector.has_table("enderecos") else set()
    if "ix_enderecos_cep" not in existing_enderecos_indexes:
        op.create_index("ix_enderecos_cep", "enderecos", ["cep"])
    if "ix_enderecos_cliente_id" not in existing_enderecos_indexes:
        op.create_index("ix_enderecos_cliente_id", "enderecos", ["cliente_id"])

    # Add endereco_id to organizacoes, keep legacy endereco string
    # Use batch_alter_table for SQLite compatibility when adding FK/index
    with op.batch_alter_table("organizacoes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("endereco_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_organizacoes_endereco_id", ["endereco_id"])
        batch_op.create_foreign_key(
            "fk_organizacoes_endereco_id_enderecos",
            "enderecos",
            ["endereco_id"], ["id"], ondelete="SET NULL"
        )


def downgrade():
    # Drop FK and column from organizacoes
    # Drop endereco_id and FK from organizacoes using batch mode for SQLite
    with op.batch_alter_table("organizacoes", schema=None) as batch_op:
        # batch_op.drop_constraint may be a no-op depending on DB, but included for clarity
        try:
            batch_op.drop_constraint("fk_organizacoes_endereco_id_enderecos", type_="foreignkey")
        except Exception:
            pass
        # Drop index and column if present
        try:
            batch_op.drop_index("ix_organizacoes_endereco_id")
        except Exception:
            pass
        try:
            batch_op.drop_column("endereco_id")
        except Exception:
            pass

    # Drop indexes from enderecos if present
    if inspector.has_table("enderecos"):
        end_indexes = {idx["name"] for idx in inspector.get_indexes("enderecos")}
        if "ix_enderecos_cliente_id" in end_indexes:
            op.drop_index("ix_enderecos_cliente_id", table_name="enderecos")
        if "ix_enderecos_cep" in end_indexes:
            op.drop_index("ix_enderecos_cep", table_name="enderecos")

    # Drop geolocation and formatted address columns from enderecos
    op.drop_column("enderecos", "place_id")
    op.drop_column("enderecos", "endereco_formatado")
    op.drop_column("enderecos", "pais")
    op.drop_column("enderecos", "longitude")
    op.drop_column("enderecos", "latitude")
