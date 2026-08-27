"""add persisted route alternatives and driver selection

Revision ID: 0013_add_route_alternatives
Revises: 0012_align_schema_with_current_models
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_add_route_alternatives"
down_revision = "0012_align_schema_with_current_models"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE tipoeventorota ADD VALUE IF NOT EXISTS 'ALTERNATIVA_RECOMENDADA'")
        op.execute("ALTER TYPE tipoeventorota ADD VALUE IF NOT EXISTS 'ALTERNATIVA_SELECIONADA'")
    elif bind.dialect.name == "mysql":
        op.execute("ALTER TABLE rota_historico MODIFY evento ENUM('PARTIDA','PAUSA','RETOMADA','ABASTECIMENTO','DESVIO','MANUTENCAO','ENTREGA_REALIZADA','ENTREGA_FALHOU','FINALIZADA','CANCELAMENTO','ALTERNATIVA_RECOMENDADA','ALTERNATIVA_SELECIONADA') NOT NULL")

    criterio = sa.Enum("MAIS_RAPIDA", "MAIS_CURTA", name="criterioalternativarota")
    op.create_table(
        "rota_alternativas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rota_id", sa.Integer(), sa.ForeignKey("rotas.id"), nullable=False),
        sa.Column("criterio", criterio, nullable=False),
        sa.Column("distancia_prevista", sa.Numeric(10, 2), nullable=False),
        sa.Column("duracao_prevista", sa.Numeric(10, 2), nullable=False),
        sa.Column("route_geometry", sa.Text()),
        sa.Column("sequencia_json", sa.Text(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("rota_id", "criterio", name="uq_rota_alternativas_rota_criterio"),
    )
    op.create_index("ix_rota_alternativas_rota_id", "rota_alternativas", ["rota_id"])

    with op.batch_alter_table("rotas") as batch:
        batch.add_column(sa.Column("alternativa_recomendada_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("alternativa_escolhida_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("alternativa_escolhida_por", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("alternativa_escolhida_em", sa.DateTime(), nullable=True))
        batch.create_index("ix_rotas_alternativa_recomendada_id", ["alternativa_recomendada_id"])
        batch.create_index("ix_rotas_alternativa_escolhida_id", ["alternativa_escolhida_id"])
        batch.create_index("ix_rotas_alternativa_escolhida_por", ["alternativa_escolhida_por"])
        batch.create_foreign_key("fk_rotas_alternativa_recomendada", "rota_alternativas", ["alternativa_recomendada_id"], ["id"])
        batch.create_foreign_key("fk_rotas_alternativa_escolhida", "rota_alternativas", ["alternativa_escolhida_id"], ["id"])
        batch.create_foreign_key("fk_rotas_alternativa_escolhida_por", "usuarios", ["alternativa_escolhida_por"], ["id"])


def downgrade():
    with op.batch_alter_table("rotas") as batch:
        for name in ("fk_rotas_alternativa_escolhida_por", "fk_rotas_alternativa_escolhida", "fk_rotas_alternativa_recomendada"):
            batch.drop_constraint(name, type_="foreignkey")
        for name in ("ix_rotas_alternativa_escolhida_por", "ix_rotas_alternativa_escolhida_id", "ix_rotas_alternativa_recomendada_id"):
            batch.drop_index(name)
        for name in ("alternativa_escolhida_em", "alternativa_escolhida_por", "alternativa_escolhida_id", "alternativa_recomendada_id"):
            batch.drop_column(name)
    op.drop_index("ix_rota_alternativas_rota_id", table_name="rota_alternativas")
    op.drop_table("rota_alternativas")
    sa.Enum(name="criterioalternativarota").drop(op.get_bind(), checkfirst=True)