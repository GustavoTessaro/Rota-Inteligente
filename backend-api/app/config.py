from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Sistema de Gerenciamento de Entregas"
    app_env: str = "development"
    database_url: str = "mysql+pymysql://entregas:senha@localhost:3306/entregas_db?charset=utf8mb4"
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
    # OAuth scope for routes optimization
    google_route_optimization_scope: str = "https://www.googleapis.com/auth/cloud-platform"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
