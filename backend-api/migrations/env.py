from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.config import settings
from app.database import Base
from app import models  # noqa: F401


config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def ensure_alembic_version_table(connection) -> None:
    """Ensure Alembic keeps a version_num long enough for historical revisions.

    Alembic's default PostgreSQL version table uses String(32), which is too short
    for revision IDs already present in this project (for example
    0008_add_organizacao_id_to_pedidos). New databases must be created with a
    wider column, and legacy PostgreSQL databases must be widened before the next
    migration records a longer revision ID.
    """
    if connection.dialect.name != "postgresql":
        return

    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(128) NOT NULL,
                PRIMARY KEY (version_num)
            )
            """
        )
    )

    connection.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'alembic_version'
                      AND column_name = 'version_num'
                ) THEN
                    ALTER TABLE alembic_version
                    ALTER COLUMN version_num TYPE VARCHAR(128);
                END IF;
            END $$;
            """
        )
    )


def run_migrations_offline():
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        ensure_alembic_version_table(connection)
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
