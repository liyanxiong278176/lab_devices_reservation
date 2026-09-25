from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from app.ai.graph.harness import AgentHarness
from app.ai.usage import _usage_scopes, estimate_reservation
from app.core.settings import Settings


def test_chat_quota_reserves_output_for_planner_and_answer_calls() -> None:
    assert estimate_reservation("问", max_output_tokens=100, context_documents=0) == 202


def test_chat_usage_scopes_have_one_shared_lock_order() -> None:
    assert _usage_scopes(user_id=7, college_id=3) == [
        ("global", 0),
        ("college", 3),
        ("user", 7),
    ]
    assert _usage_scopes(user_id=7, college_id=None) == [("global", 0), ("user", 7)]


def test_each_chat_model_call_receives_the_configured_output_cap(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    fake_provider = ModuleType("langchain_openai")
    fake_provider.ChatOpenAI = FakeChatOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_provider)

    harness = AgentHarness.__new__(AgentHarness)
    harness.runtime = SimpleNamespace(
        model="test-model",
        api_key="not-a-real-key",
        base_url="https://invalid.example",
    )
    harness.settings = Settings(environment="test", ai_max_output_tokens=321)

    harness._create_chat_model(temperature=0)
    harness._create_chat_model(temperature=0.1, stream_usage=True)

    assert len(calls) == 2
    assert [call["max_tokens"] for call in calls] == [321, 321]
    assert calls[1]["stream_usage"] is True
