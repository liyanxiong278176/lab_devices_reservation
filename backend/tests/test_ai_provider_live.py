from __future__ import annotations

import asyncio
import os

import httpx
import pytest


@pytest.mark.asyncio
async def test_ci_can_reach_official_deepseek_chat_model() -> None:
    """Each CI run makes one bounded, real provider call; local unit runs skip it."""
    if os.getenv("CI", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("live provider checks run only in CI")

    api_key = os.getenv("LAB_AI_CI_DEEPSEEK_KEY")
    assert api_key, "CI requires the LAB_AI_CI_DEEPSEEK_KEY repository secret"

    payload = {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "Reply with the single word OK."}],
        "max_tokens": 8,
        "stream": False,
    }
    status = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        for attempt in range(2):
            try:
                response = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                status = response.status_code
                if status not in {429, 500, 502, 503, 504} or attempt == 1:
                    break
            except httpx.TimeoutException:
                if attempt == 1:
                    raise AssertionError("DeepSeek live check timed out after one retry") from None
            await asyncio.sleep(0.5)

    assert status == 200, f"DeepSeek live check failed with HTTP {status}"
    data = response.json()
    assert data.get("model") == "deepseek-flash"
    assert data.get("choices") and data["choices"][0].get("message", {}).get("content")
