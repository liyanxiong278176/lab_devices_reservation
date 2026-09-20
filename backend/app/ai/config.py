from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import Principal, college_scope
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import AiProviderConfig


@dataclass(frozen=True)
class AiRuntimeConfig:
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    enabled: bool


def _fernet(settings: Settings) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key)


def encrypt_api_key(settings: Settings, api_key: str) -> str:
    return _fernet(settings).encrypt(api_key.encode()).decode()


def decrypt_api_key(settings: Settings, ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet(settings).decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        raise ApiError("AI_CONFIG_INVALID", "AI 密钥无法解密，请重新配置", 500) from None


def validate_provider_config(settings: Settings, *, model: str, base_url: str | None) -> None:
    if model not in settings.ai_allowed_models:
        raise ApiError("AI_MODEL_NOT_ALLOWED", "该模型不在系统允许列表中", 422)
    if base_url is None:
        return
    parsed = urlparse(base_url)
    normalized = base_url.rstrip("/")
    allowed = {item.rstrip("/") for item in settings.ai_allowed_base_urls}
    if parsed.scheme != "https" or normalized not in allowed:
        raise ApiError("AI_BASE_URL_NOT_ALLOWED", "AI 服务地址不在系统白名单中", 422)


async def get_runtime_config(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
) -> AiRuntimeConfig | None:
    scope = college_scope(principal)
    config = None
    # A college override must win over global configuration. Lexicographic
    # ordering of scope keys is not a safe way to express that precedence.
    if scope is not None:
        config = await session.scalar(
            select(AiProviderConfig).where(
                AiProviderConfig.scope_key == f"college:{scope}",
                AiProviderConfig.enabled.is_(True),
            )
        )
    if config is None:
        config = await session.scalar(
            select(AiProviderConfig).where(
                AiProviderConfig.scope_key == "global",
                AiProviderConfig.enabled.is_(True),
            )
        )
    if config is not None:
        return AiRuntimeConfig(
            provider=config.provider,
            model=config.model,
            api_key=decrypt_api_key(settings, config.api_key_encrypted),
            base_url=config.base_url,
            enabled=config.enabled,
        )
    if settings.environment in {"local", "test", "dev"} and settings.ai_api_key:
        validate_provider_config(settings, model=settings.ai_model, base_url=settings.ai_base_url)
        return AiRuntimeConfig(
            provider=settings.ai_provider,
            model=settings.ai_model,
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            enabled=True,
        )
    return None


def config_scope(principal: Principal) -> tuple[str, int | None]:
    if principal.is_system_admin:
        return "global", None
    scope = college_scope(principal)
    if not principal.is_lab_admin or scope is None:
        raise ApiError("FORBIDDEN", "只有系统管理员或学院负责人可以管理 AI 配置", 403)
    return f"college:{scope}", scope
