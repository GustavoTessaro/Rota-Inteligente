import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

from .runtime_paths import is_packaged_runtime, resolve_database_url


class Settings(BaseSettings):
    app_name: str = "Sistema de Gerenciamento de Entregas"
    app_env: str = "development"
    database_url: str | None = None
    jwt_secret: str = "troque-este-segredo-em-producao-com-mais-de-32-bytes"
    jwt_expires_minutes: int = 480
    cors_origins: str = "*"
    seed_database: bool = True
    # Google Maps configuration
    google_maps_api_key: str | None = None
    google_maps_restricted_key: str | None = None
    # Geocoding provider: 'google' or 'nominatim'
    geocoding_provider: str = "nominatim"
    # Optional contact email for Nominatim usage policy
    nominatim_email: str | None = None
    # default map center (lat,lng) shown when no data
    maps_default_center: str = "-23.55052,-46.633308"  # São Paulo as default
    # Route Optimization config
    use_google_route_optimization: bool = False
    # Path to service account JSON file for Google Cloud
    google_route_optimization_service_account_file: str | None = None
    # Optional explicit endpoint for Route Optimization API (useful for testing)
    google_route_optimization_endpoint: str | None = None
    google_route_optimization_project_id: str | None = None
    google_route_optimization_location: str = "us-central1"
    # OAuth scope for routes optimization
    google_route_optimization_scope: str = "https://www.googleapis.com/auth/cloud-platform"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",")]


def normalize_database_url(database_url: str) -> str:
    value = database_url.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


def validate_database_url(app_env: str, database_url: str | None) -> str:
    value = normalize_database_url(database_url or "")
    if app_env != "production":
        return value
    if not value:
        raise ValueError("DATABASE_URL é obrigatória em production e deve apontar para PostgreSQL.")
    if value.startswith("sqlite:"):
        raise ValueError("DATABASE_URL não pode usar SQLite em production; configure PostgreSQL.")
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql+psycopg" or not parsed.hostname:
        raise ValueError("DATABASE_URL inválida em production; use uma URL PostgreSQL válida.")
    return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    explicit_database_url = os.environ.get("DATABASE_URL", "").strip()
    if explicit_database_url:
        settings.database_url = explicit_database_url

    if settings.app_env == "production":
        settings.database_url = validate_database_url(settings.app_env, settings.database_url)
        return settings

    if is_packaged_runtime() and not explicit_database_url:
        settings.database_url = resolve_database_url()
    elif not settings.database_url:
        settings.database_url = resolve_database_url()
    else:
        settings.database_url = normalize_database_url(settings.database_url)

    return settings


settings = get_settings()
