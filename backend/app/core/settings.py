"""Configuration for optional SQL/Redis test tools, with no HTTP server."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAB_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )
    environment: str = "local"
    debug: bool = False
    mysql_dsn: str = "mysql+asyncmy://lab_runtime@127.0.0.1:3306/lab_reservation?charset=utf8mb4"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_socket_timeout_seconds: float = 0.5
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800
    db_pool_timeout_seconds: int = 10
    upload_dir: str = ".data/uploads"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
