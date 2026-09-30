from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from langchain_core.messages import HumanMessage

from app.ai.config import AiRuntimeConfig
from app.core.errors import ApiError
from app.core.settings import Settings


@dataclass(frozen=True)
class ProviderTestResult:
    success: bool
    message: str
    latency_ms: int


async def test_provider(
    component: str,
    runtime: AiRuntimeConfig,
    settings: Settings,
) -> ProviderTestResult:
    if not runtime.api_key:
        raise ApiError("AI_KEY_REQUIRED", "请先在后端 .env 配置对应服务的 API Key 并重启", 422)
    started = time.perf_counter()
    try:
        if component == "chat":
            from langchain_openai import ChatOpenAI

            model = ChatOpenAI(
                model=runtime.model,
                api_key=runtime.api_key,
                base_url=runtime.base_url,
                temperature=0,
                max_tokens=8,
                timeout=min(settings.ai_provider_timeout_seconds, 12),
                max_retries=1,
            )
            await model.ainvoke([HumanMessage(content="只回复 OK")])
        elif component == "embedding":
            from langchain_openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings(
                model=runtime.model,
                api_key=runtime.api_key,
                base_url=runtime.base_url,
                timeout=min(settings.ai_provider_timeout_seconds, 12),
                max_retries=1,
                # Ollama's OpenAI-compatible endpoint accepts text strings,
                # but not LangChain's token-ID arrays.
                check_embedding_ctx_length=runtime.provider.lower() != "ollama",
            )
            vector = await embeddings.aembed_query("实验室设备配置连通性检测")
            if len(vector) != settings.ai_embedding_dimension:
                dimension_message = (
                    f"Embedding 返回 {len(vector)} 维，"
                    f"系统索引要求 {settings.ai_embedding_dimension} 维"
                )
                raise ApiError(
                    "AI_EMBEDDING_DIMENSION_MISMATCH",
                    dimension_message,
                    422,
                )
        elif component == "mineru":
            # MinerU's authenticated task endpoint validates the bearer token;
            # a deliberately nonexistent task must be rejected as a task, not
            # as an authentication failure.
            async with httpx.AsyncClient(
                base_url=settings.ai_mineru_base_url.rstrip("/"),
                timeout=min(settings.ai_provider_timeout_seconds, 12),
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    "/api/v4/extract/task/config-probe-not-a-real-task",
                    headers={"Authorization": f"Bearer {runtime.api_key}"},
                )
            if response.status_code in {401, 403}:
                raise ApiError("AI_PROVIDER_AUTH_FAILED", "MinerU API Key 无效", 422)
            if response.status_code == 429 or response.status_code >= 500:
                raise ApiError("AI_PROVIDER_UNAVAILABLE", "MinerU 服务暂时不可用", 503)
            if response.status_code >= 400:
                raise ApiError("AI_PROVIDER_TEST_FAILED", "MinerU 连接测试失败", 502)
            if response.status_code != 200:
                raise ApiError("AI_PROVIDER_TEST_FAILED", "MinerU 连接测试未得到有效响应", 502)
            try:
                payload = response.json()
            except ValueError as exc:
                raise ApiError("AI_PROVIDER_TEST_FAILED", "MinerU 返回了无效响应", 502) from exc
            if not isinstance(payload, dict):
                raise ApiError("AI_PROVIDER_TEST_FAILED", "MinerU 返回了无效响应", 502)
            code = payload.get("code")
            message = str(payload.get("msg", "")).casefold()
            # The probe deliberately uses a nonexistent task ID; MinerU
            # authenticates it and returns this task-level result.
            if code != 0 and not (code == -60012 and "task not found" in message):
                raise ApiError(
                    "AI_PROVIDER_TEST_FAILED",
                    "MinerU 服务返回错误，连接测试未通过",
                    502,
                )
        else:
            raise ApiError("AI_COMPONENT_INVALID", "未知的 AI 服务类型", 422)
    except ApiError:
        raise
    except Exception as exc:
        # Provider SDK errors can contain request headers; never return or log
        # raw exception text where an API key could be reflected.
        raise ApiError(
            "AI_PROVIDER_TEST_FAILED", "连接测试失败，请检查模型、地址和 API Key", 502
        ) from exc
    return ProviderTestResult(
        success=True,
        message="连接成功，模型可以正常响应",
        latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
    )
