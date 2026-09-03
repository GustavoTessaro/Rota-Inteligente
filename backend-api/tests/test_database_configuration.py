import asyncio
from unittest.mock import patch

import pytest

from app.config import normalize_database_url, validate_database_url


def test_development_allows_sqlite():
    assert validate_database_url("development", "sqlite:///./test_entregas.db") == "sqlite:///./test_entregas.db"


def test_test_allows_sqlite():
    assert validate_database_url("test", "sqlite:///./test_entregas.db") == "sqlite:///./test_entregas.db"


def test_production_requires_database_url():
    with pytest.raises(ValueError, match="DATABASE_URL é obrigatória"):
        validate_database_url("production", None)


def test_production_rejects_sqlite():
    with pytest.raises(ValueError, match="não pode usar SQLite"):
        validate_database_url("production", "sqlite:///./test_entregas.db")


def test_production_normalizes_postgresql_url():
    assert validate_database_url("production", "postgresql://user:password@db:5432/app") == (
        "postgresql+psycopg://user:password@db:5432/app"
    )


def test_postgresql_scheme_normalization_preserves_psycopg_url():
    url = "postgresql+psycopg://user:password@db:5432/app"
    assert normalize_database_url(url) == url


def test_psycopg3_is_importable():
    import psycopg

    assert tuple(int(part) for part in psycopg.__version__.split(".")[:2]) >= (3, 0)


def test_production_lifespan_skips_create_all_and_seed(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "app_env", "production")
    monkeypatch.setattr(main_module.settings, "seed_database", True)
    async def run_lifespan():
        async with main_module.lifespan(None):
            pass

    with patch.object(main_module.Base.metadata, "create_all") as create_all:
        with patch.object(main_module, "seed_database") as seed:
            asyncio.run(run_lifespan())

    create_all.assert_not_called()
    seed.assert_not_called()