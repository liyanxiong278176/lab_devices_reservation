import httpx
import pytest
from app.ai.config import AiRuntimeConfig
from app.ai.providers import test_provider as run_provider_test
from app.core.errors import ApiError
from app.core.settings import Settings


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [302, 429, 500, 503])
async def test_mineru_connection_check_rejects_redirects_throttling_and_server_errors(
    monkeypatch, status_code: int
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(status_code))
    original_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr("app.ai.providers.httpx.AsyncClient", mock_client)
    runtime = AiRuntimeConfig("mineru", "model", "dummy-key", "https://mineru.net", True)

    with pytest.raises(ApiError):
        await run_provider_test("mineru", runtime, Settings(environment="test"))


@pytest.mark.asyncio
async def test_mineru_connection_check_accepts_only_the_expected_missing_task_response(
    monkeypatch,
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"code": -60012, "msg": "task not found or expire"},
        )
    )
    original_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr("app.ai.providers.httpx.AsyncClient", mock_client)
    runtime = AiRuntimeConfig("mineru", "model", "dummy-key", "https://mineru.net", True)

    result = await run_provider_test("mineru", runtime, Settings(environment="test"))

    assert result.success


@pytest.mark.asyncio
async def test_mineru_connection_check_rejects_unexpected_provider_business_error(
    monkeypatch,
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"code": -10001, "msg": "quota exceeded"})
    )
    original_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr("app.ai.providers.httpx.AsyncClient", mock_client)
    runtime = AiRuntimeConfig("mineru", "model", "dummy-key", "https://mineru.net", True)

    with pytest.raises(ApiError):
        await run_provider_test("mineru", runtime, Settings(environment="test"))
