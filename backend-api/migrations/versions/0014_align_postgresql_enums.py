"""align PostgreSQL enum values with current models

Revision ID: 0014_align_postgresql_enums
Revises: 0013_add_route_alternatives
"""

from alembic import op


revision = "0014_align_postgresql_enums"
down_revision = "0013_add_route_alternatives"
branch_labels = None
depends_on = None


STATUSROTA_VALUES = (
    "RASCUNHO",
    "OTIMIZANDO",
    "AGUARDANDO_ACEITE",
    "CONCLUIDA",
)
TIPOEVENTOROTA_VALUES = ("CANCELAMENTO",)


def _add_enum_values(enum_name: str, values: tuple[str, ...]) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for value in values:
        escaped_value = value.replace("'", "''")
        op.execute(
            f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{escaped_value}'"
        )


def upgrade() -> None:
    _add_enum_values("statusrota", STATUSROTA_VALUES)
    _add_enum_values("tipoeventorota", TIPOEVENTOROTA_VALUES)


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely without recreating the type.
    # Keep the values to avoid data loss; Alembic still records revision 0013.
    pass
