from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAB_",
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Laboratory Reservation API"
    api_version: str = "2.0.0"
    api_prefix: str = "/api/v2"
    environment: Literal["local", "test", "dev", "prod"] = "local"
    debug: bool = False
    mysql_dsn: str = "mysql+asyncmy://root:123456@127.0.0.1:3306/lab_reservation?charset=utf8mb4"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_socket_timeout_seconds: float = 0.5
    redis_circuit_failure_threshold: int = 3
    redis_circuit_recovery_seconds: float = 5.0
    qdrant_url: str = "http://127.0.0.1:6333"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    jwt_secret: str = "dev-only-change-this-secret-32chars-minimum"
    jwt_issuer: str = "lab-reservation"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    enable_workers: bool = True
    bootstrap_admin_username: str = Field(default="admin", min_length=3, max_length=64)
    bootstrap_admin_password: str | None = Field(default=None, min_length=8, max_length=128)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 10
    db_pool_recycle_seconds: int = 1800
    outbox_claim_timeout_seconds: int = 300
    outbox_max_attempts: int = 5
    outbox_retry_base_seconds: int = 5
    outbox_worker_concurrency: int = 4
    outbox_task_timeout_seconds: float = 30.0
    upload_dir: str = ".data/uploads"
    upload_max_bytes: int = 5 * 1024 * 1024
    reservation_max_days: int = 31
    reservation_advance_days: int = 30
    reservation_manager_advance_days: int = 90
    reservation_lock_ttl_seconds: int = 8
    reservation_lock_wait_seconds: float = 2.0
    reservation_lock_poll_seconds: float = 0.05
    reservation_user_active_limit: int = 10
    reservation_user_days_limit: int = 31
    credit_block_threshold: int = 60
    credit_block_days: int = 7
    cache_default_ttl_seconds: int = 300
    cache_negative_ttl_seconds: int = 30
    cache_ttl_jitter_seconds: int = 60
    cache_hot_key_lock_seconds: int = 3
    cache_hot_key_wait_seconds: float = 0.5
    rate_limit_enabled: bool = True
    rate_limit_redis_timeout_seconds: float = 0.25
    rate_limit_local_max_entries: int = 10000
    rate_limit_default_capacity: int = 60
    rate_limit_default_refill_per_second: float = 1.0
    rate_limit_login_capacity: int = 5
    rate_limit_login_refill_per_second: float = 5 / 60
    rate_limit_reservation_capacity: int = 10
    rate_limit_reservation_refill_per_second: float = 10 / 60
    rate_limit_repair_capacity: int = 10
    rate_limit_repair_refill_per_second: float = 10 / 60
    repair_sla_days: dict[str, int] = Field(
        default_factory=lambda: {"NORMAL": 3, "IMPORTANT": 2, "URGENT": 1}
    )
    repair_user_confirmation_days: int = 3
    export_sync_row_limit: int = 1000
    recommend_cache_ttl_seconds: int = 300
    ai_provider: str = "openai"
    ai_model: str = "gpt-4o-mini"
    ai_allowed_models: list[str] = Field(
        default_factory=lambda: [
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "Qwen/Qwen2.5-72B-Instruct",
            "deepseek-ai/DeepSeek-V3",
        ]
    )
    ai_api_key: str | None = None
    ai_base_url: str | None = None
    ai_allowed_base_urls: list[str] = Field(
        default_factory=lambda: [
            "https://api.openai.com/v1",
            "https://api.siliconflow.cn/v1",
        ]
    )
    ai_embedding_model: str = "text-embedding-3-small"
    ai_embedding_dimension: int = 1536
    ai_qdrant_collection: str = "lab_knowledge_v2"
    ai_qdrant_timeout_seconds: int = 5
    ai_max_context_documents: int = 6
    ai_confirmation_ttl_minutes: int = 10
    ai_max_input_chars: int = 8000

    @model_validator(mode="after")
    def validate_runtime_security(self) -> "Settings":
        if self.environment == "prod":
            if len(self.jwt_secret) < 32 or self.jwt_secret.startswith("dev-only"):
                raise ValueError("生产环境必须设置独立且长度不少于 32 的 LAB_JWT_SECRET")
            if "123456" in self.mysql_dsn or "password" in self.mysql_dsn.lower():
                raise ValueError("生产环境禁止使用默认数据库密码")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
