from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAB_",
        env_file=PROJECT_ROOT / ".env",
        env_ignore_empty=True,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Laboratory Reservation API"
    api_version: str = "2.0.0"
    api_prefix: str = "/api/v2"
    environment: Literal["local", "test", "dev", "prod"] = "local"
    debug: bool = False
    # Local runtime uses a schema-scoped account; credentials belong in the root .env.
    mysql_dsn: str = "mysql+asyncmy://lab_runtime@127.0.0.1:3306/lab_reservation?charset=utf8mb4"
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str = "redis://127.0.0.1:6379/1"
    celery_visibility_timeout_seconds: int = Field(default=7_260, ge=60, le=86_400)
    celery_task_soft_time_limit_seconds: int = Field(default=7_140, ge=60, le=86_400)
    celery_task_time_limit_seconds: int = Field(default=7_200, ge=60, le=86_400)
    celery_worker_concurrency: int = Field(default=1, ge=1, le=16)
    ai_knowledge_build_embed_batch_size: int = Field(default=32, ge=1, le=256)
    ai_knowledge_build_lease_seconds: int = Field(default=300, ge=30, le=3_600)
    ai_knowledge_build_dispatch_recovery_seconds: int = Field(default=600, ge=60, le=86_400)
    ai_knowledge_build_reconcile_interval_seconds: int = Field(default=30, ge=5, le=3_600)
    ai_knowledge_build_max_redeliveries: int = Field(default=3, ge=1, le=20)
    redis_socket_timeout_seconds: float = 0.5
    redis_circuit_failure_threshold: int = 3
    redis_circuit_recovery_seconds: float = 5.0
    qdrant_url: str = "http://127.0.0.1:6333"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    # Metrics are disabled unless an operator configures a scrape token.
    metrics_token: str | None = None
    # Forwarding headers are only honored when the direct peer is explicitly trusted.
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    jwt_secret: str = "dev-only-change-this-secret-32chars-minimum"
    jwt_issuer: str = "lab-reservation"
    jwt_audience: str = "lab-reservation-web"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    access_cookie_name: str = "lab_access"
    refresh_cookie_name: str = "lab_refresh"
    csrf_cookie_name: str = "lab_csrf"
    cookie_secure: bool = False
    allow_insecure_cookie_for_testing: bool = False
    cookie_domain: str | None = None
    enable_workers: bool = True
    bootstrap_admin_username: str = Field(default="admin", min_length=3, max_length=64)
    bootstrap_admin_password: str | None = Field(default=None, min_length=8, max_length=128)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 10
    db_pool_recycle_seconds: int = 1800
    request_queue_capacity: int = Field(default=1000, ge=0, le=10000)
    request_health_capacity: int = 8
    outbox_claim_timeout_seconds: int = 300
    outbox_max_attempts: int = 5
    outbox_retry_base_seconds: int = 5
    outbox_worker_concurrency: int = 4
    outbox_task_timeout_seconds: float = 30.0
    upload_dir: str = ".data/uploads"
    upload_max_bytes: int = 5 * 1024 * 1024
    upload_user_quota_bytes: int = 100 * 1024 * 1024
    upload_college_quota_bytes: int = 1024 * 1024 * 1024
    upload_total_quota_bytes: int = 2 * 1024 * 1024 * 1024
    upload_orphan_retention_hours: int = 24
    upload_cleanup_interval_seconds: int = 3600
    notification_sse_max_connections: int = Field(default=500, ge=1, le=10000)
    notification_sse_max_per_user: int = Field(default=5, ge=1, le=100)
    notification_sse_max_pending: int = Field(default=100, ge=1, le=1000)
    notification_sse_max_pending_per_ip: int = Field(default=5, ge=1, le=100)
    notification_sse_auth_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    notification_sse_heartbeat_seconds: float = Field(default=20.0, ge=5, le=120)
    notification_sse_revalidate_seconds: float = Field(default=60.0, ge=10, le=600)
    notification_sse_max_replay_events: int = Field(default=100, ge=1, le=100)
    reservation_max_days: int = 31
    reservation_advance_days: int = 30
    reservation_manager_advance_days: int = 90
    reservation_lock_ttl_seconds: int = 8
    reservation_lock_wait_seconds: float = 2.0
    reservation_lock_poll_seconds: float = 0.05
    reservation_quota_reconcile_interval_seconds: int = Field(default=60, ge=10, le=3600)
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
    # Page loads fan out into several authenticated reads. Keep the shared
    # IP/college buckets high enough for normal navigation while the
    # user-scoped bucket still limits a single noisy client.
    rate_limit_default_capacity: int = 300
    rate_limit_default_refill_per_second: float = 5.0
    rate_limit_login_ip_capacity: int = 30
    rate_limit_login_ip_refill_per_second: float = 30 / 60
    rate_limit_login_capacity: int = 5
    rate_limit_login_refill_per_second: float = 5 / 60
    rate_limit_reservation_capacity: int = 10
    rate_limit_reservation_refill_per_second: float = 10 / 60
    rate_limit_repair_capacity: int = 10
    rate_limit_repair_refill_per_second: float = 10 / 60
    rate_limit_upload_capacity: int = 60
    rate_limit_upload_refill_per_second: float = 1 / 60
    rate_limit_register_ip_capacity: int = 10
    rate_limit_register_ip_refill_per_second: float = 10 / 3600
    rate_limit_register_username_capacity: int = 3
    rate_limit_register_username_refill_per_second: float = 3 / 86400
    repair_sla_days: dict[str, int] = Field(
        default_factory=lambda: {"NORMAL": 3, "IMPORTANT": 2, "URGENT": 1}
    )
    repair_user_confirmation_days: int = 3
    export_sync_row_limit: int = 1000
    recommend_cache_ttl_seconds: int = 300
    ai_provider: str = "deepseek"
    ai_model: str = "deepseek-flash"
    ai_allowed_models: list[str] = Field(default_factory=lambda: ["deepseek-flash"])
    ai_api_key: str | None = None
    ai_base_url: str = "https://api.deepseek.com"
    ai_allowed_base_urls: list[str] = Field(
        default_factory=lambda: [
            "https://api.deepseek.com",
            "https://api.deepseek.com/v1",
            "https://api.siliconflow.cn/v1",
        ]
    )
    ai_embedding_provider: str = "siliconflow"
    ai_embedding_model: str = "BAAI/bge-m3"
    ai_embedding_api_key: str | None = None
    ai_embedding_base_url: str = "https://api.siliconflow.cn/v1"
    ai_embedding_dimension: int = 1024
    ai_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    ai_mineru_model: str = "vlm"
    ai_mineru_api_key: str | None = None
    ai_mineru_base_url: str = "https://mineru.net"
    ai_user_daily_token_cap: int = Field(default=100_000, gt=0, le=100_000_000)
    ai_college_daily_token_cap: int = Field(default=1_000_000, gt=0, le=1_000_000_000)
    ai_global_daily_token_cap: int = Field(default=10_000_000, gt=0, le=10_000_000_000)
    ai_qdrant_collection: str = "lab_knowledge_v2"
    ai_qdrant_timeout_seconds: int = 5
    ai_rag_query_concurrency: int = Field(default=4, ge=1, le=16)
    ai_max_context_documents: int = 6
    ai_confirmation_ttl_minutes: int = 10
    ai_max_input_chars: int = 8000
    ai_max_output_tokens: int = 2048
    ai_daily_reservation_tokens: int = 4096
    ai_run_event_poll_seconds: float = 0.5
    ai_run_event_heartbeat_seconds: float = 15.0
    ai_message_retention_days: int = 180
    ai_upload_max_bytes: int = 20 * 1024 * 1024
    ai_knowledge_global_storage_bytes: int = 1024 * 1024 * 1024
    ai_knowledge_college_storage_bytes: int = 512 * 1024 * 1024
    ai_provider_timeout_seconds: float = 45.0

    @model_validator(mode="after")
    def validate_runtime_security(self) -> "Settings":
        if self.celery_task_soft_time_limit_seconds >= self.celery_task_time_limit_seconds:
            raise ValueError("Celery hard task limit must exceed its soft task limit")
        if self.celery_visibility_timeout_seconds <= self.celery_task_time_limit_seconds:
            raise ValueError("Celery Redis visibility timeout must exceed the hard task limit")
        if self.environment == "prod":
            if not self.cookie_secure and not self.allow_insecure_cookie_for_testing:
                raise ValueError("生产环境必须启用 LAB_COOKIE_SECURE")
            secret = self.jwt_secret.strip().lower()
            if (
                len(secret) < 32
                or secret.startswith("dev-only")
                or secret.startswith(("replace-with", "change-me", "your-", "placeholder"))
            ):
                raise ValueError("生产环境必须设置独立且长度不少于 32 的 LAB_JWT_SECRET")
            database_url = make_url(self.mysql_dsn)
            database_password = (database_url.password or "").lower()
            if (
                database_url.username in {None, "root"}
                or not database_url.password
                or "123456" in database_password
                or "password" in database_password
                or "change-me" in database_password
                or "replace-with" in database_password
            ):
                raise ValueError("生产环境必须使用非 root 数据库账号和独立强密码")
            missing_ai_keys = [
                name
                for name, value in (
                    ("LAB_AI_API_KEY", self.ai_api_key),
                    ("LAB_AI_EMBEDDING_API_KEY", self.ai_embedding_api_key),
                    ("LAB_AI_MINERU_API_KEY", self.ai_mineru_api_key),
                )
                if not value or not value.strip()
            ]
            if missing_ai_keys:
                raise ValueError(f"生产环境必须配置 AI 密钥：{', '.join(missing_ai_keys)}")
        if self.metrics_token and len(self.metrics_token) < 32:
            raise ValueError("LAB_METRICS_TOKEN 配置后必须至少 32 个字符")
        if self.environment == "prod" and not self.metrics_token:
            raise ValueError("生产环境必须配置 LAB_METRICS_TOKEN 以启用受保护的指标抓取")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
