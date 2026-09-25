from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import Principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import AiKnowledgeIndexState

AiComponent = Literal["chat", "embedding", "mineru"]


@dataclass(frozen=True)
class AiRuntimeConfig:
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    enabled: bool
    collection_name: str | None = None


def _clean_key(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None


def runtime_config(settings: Settings, component: AiComponent) -> AiRuntimeConfig:
    """Build provider configuration exclusively from process environment settings."""
    if component == "chat":
        api_key = _clean_key(settings.ai_api_key)
        return AiRuntimeConfig(
            provider=settings.ai_provider,
            model=settings.ai_model,
            api_key=api_key,
            base_url=settings.ai_base_url,
            enabled=api_key is not None,
        )
    if component == "embedding":
        api_key = _clean_key(settings.ai_embedding_api_key)
        return AiRuntimeConfig(
            provider=settings.ai_embedding_provider,
            model=settings.ai_embedding_model,
            api_key=api_key,
            base_url=settings.ai_embedding_base_url,
            enabled=api_key is not None,
            collection_name=settings.ai_qdrant_collection,
        )
    if component == "mineru":
        api_key = _clean_key(settings.ai_mineru_api_key)
        return AiRuntimeConfig(
            provider="mineru",
            model=settings.ai_mineru_model,
            api_key=api_key,
            base_url=settings.ai_mineru_base_url,
            enabled=api_key is not None,
        )
    raise ApiError("AI_COMPONENT_INVALID", "未知的 AI 服务类型", 404)


def config_fingerprint(settings: Settings, runtime: AiRuntimeConfig) -> str:
    """Persist only a keyed fingerprint, never a provider credential, in task rows."""
    secret = _clean_key(runtime.api_key) or ""
    payload = "\0".join(
        (runtime.provider, runtime.model, runtime.base_url or "", secret)
    ).encode()
    return hmac.new(settings.jwt_secret.encode(), payload, hashlib.sha256).hexdigest()


def validate_provider_config(
    settings: Settings,
    *,
    model: str,
    base_url: str | None,
    component: str = "chat",
) -> None:
    allowed_models = {
        "chat": set(settings.ai_allowed_models),
        "embedding": {settings.ai_embedding_model},
        "mineru": {settings.ai_mineru_model},
    }.get(component, set())
    if model not in allowed_models:
        raise ApiError("AI_MODEL_NOT_ALLOWED", "该模型不在环境配置允许列表中", 422)
    if base_url is None:
        return
    parsed = urlparse(base_url)
    normalized = base_url.rstrip("/")
    if component == "mineru":
        if parsed.scheme != "https" or normalized != settings.ai_mineru_base_url.rstrip("/"):
            raise ApiError("AI_BASE_URL_NOT_ALLOWED", "MinerU 服务地址不可自定义", 422)
        return
    allowed = {item.rstrip("/") for item in settings.ai_allowed_base_urls}
    if parsed.scheme != "https" or normalized not in allowed:
        raise ApiError("AI_BASE_URL_NOT_ALLOWED", "AI 服务地址不在系统白名单中", 422)


async def get_runtime_config(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
) -> AiRuntimeConfig:
    del session, principal  # Provider settings are server-side environment configuration.
    return runtime_config(settings, "chat")


async def get_component_config(
    session: AsyncSession,
    settings: Settings,
    component: str,
) -> AiRuntimeConfig:
    if component not in {"chat", "embedding", "mineru"}:
        raise ApiError("AI_COMPONENT_INVALID", "未知的 AI 服务类型", 404)
    config = runtime_config(settings, component)  # type: ignore[arg-type]
    if component == "embedding":
        active_collection = await session.scalar(
            select(AiKnowledgeIndexState.collection_name).where(
                AiKnowledgeIndexState.component == "embedding"
            )
        )
        if active_collection:
            return replace(config, collection_name=active_collection)
    return config


def config_scope(principal: Principal) -> tuple[str, int | None]:
    if principal.is_system_admin:
        return "environment", None
    raise ApiError("FORBIDDEN", "只有系统管理员可以查看全局 AI 服务状态", 403)
