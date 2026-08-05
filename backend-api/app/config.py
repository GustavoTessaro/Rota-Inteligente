from functools import lru_cache

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
    # default map center (lat,lng) shown when no data
    maps_default_center: str = "-23.55052,-46.633308"  # São Paulo as default

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
