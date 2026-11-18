from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Cari .env di root monorepo (apps/api/src/bhv -> root) lalu di apps/api.
_ROOT = Path(__file__).resolve().parents[4]
_ENV_FILES = (_ROOT / ".env", Path(__file__).resolve().parents[2] / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://bhv:bhv@localhost:5433/bhv"
    # DB khusus test; di-DROP & dibuat ulang setiap sesi pytest. Jangan arahkan ke DB produksi.
    test_database_url: str = "postgresql+psycopg://bhv:bhv@localhost:5433/bhv_test"
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    cookie_secure: bool = False
    cookie_name: str = "bhv_session"
    timezone: str = "Asia/Jakarta"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip().rstrip("/") for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
