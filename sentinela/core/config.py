"""
Sentinela HL — configuração central (carregada do ambiente).

Defaults batem com o Documento 110: Supabase no host via host.docker.internal,
Redis e Evolution nos nomes de serviço do compose. Segredos vêm do ambiente
(.env), nunca hardcoded.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SENTINELA_",
        extra="ignore",
    )

    # --- Supabase (host, via CLI) -------------------------------------
    # De dentro de um container use host.docker.internal; rodando no host, localhost.
    supabase_url: str = "http://host.docker.internal:54321"
    supabase_db_host: str = "host.docker.internal"
    supabase_db_port: int = 54322
    supabase_db_name: str = "postgres"
    supabase_db_user: str = "postgres"
    supabase_db_password: str = Field(default="postgres")  # local; sobrescrever em prod
    supabase_service_key: str = Field(default="")          # p/ REST/RLS bypass

    # --- Anthropic (o cérebro dos filtros) ----------------------------
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = "claude-opus-4-x"               # ajustar ao modelo vigente

    # --- Redis / Evolution --------------------------------------------
    redis_uri: str = "redis://localhost:6379"
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = Field(default="")

    # --- Retenção da higienização (espelha o Documento 103) -----------
    raw_items_retention_days: int = 7
    fetch_runs_retention_days: int = 30

    # --- Operacional --------------------------------------------------
    log_level: str = "INFO"
    timezone: str = "America/Sao_Paulo"

    @property
    def db_dsn(self) -> str:
        """DSN psycopg para o Postgres do Supabase."""
        return (
            f"postgresql://{self.supabase_db_user}:{self.supabase_db_password}"
            f"@{self.supabase_db_host}:{self.supabase_db_port}/{self.supabase_db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instância única de Settings (carrega o ambiente uma vez)."""
    return Settings()
