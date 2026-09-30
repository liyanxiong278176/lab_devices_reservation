from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from app.ai.graph.harness import AgentHarness
from app.ai.usage import (
    _usage_scopes,
    estimate_reservation,
    reserve_additional_chat_tokens,
    reserve_chat_tokens,
    settle_chat_tokens,
)
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import (
    AiConversation,
    AiRun,
    AiUsageBucket,
    AiUsageEvent,
)
from sqlalchemy import select


def test_chat_quota_reserves_output_for_rewrite_planner_and_answer_calls() -> None:
    assert estimate_reservation("问", max_output_tokens=100, context_documents=0) == 302


def test_chat_usage_scopes_have_one_shared_lock_order() -> None:
    assert _usage_scopes(user_id=7, college_id=3) == [
        ("global", 0),
        ("college", 3),
        ("user", 7),
    ]
    assert _usage_scopes(user_id=7, college_id=None) == [("global", 0), ("user", 7)]


@pytest.mark.asyncio
async def test_additional_planner_quota_reservation_is_idempotent(seeded) -> None:
    factory, college, _, user, *_ = seeded
    settings = Settings(
        environment="test",
        ai_global_daily_token_cap=1000,
        ai_college_daily_token_cap=800,
        ai_user_daily_token_cap=500,
    )
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="额度预留测试",
            graph_thread_id="quota-reservation-idempotency",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="quota-reservation-idempotency",
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            status="RUNNING",
            input_text="查询设备并确认可用性",
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        await reserve_chat_tokens(
            session,
            settings=settings,
            run_id=run_id,
            user_id=user.id,
            college_id=college.id,
            token_reservation=100,
        )
        await session.commit()

        first = await reserve_additional_chat_tokens(
            session,
            settings=settings,
            run_id=run_id,
            reservation_key="planner-after-tool-results-abc",
            token_reservation=70,
        )
        duplicate = await reserve_additional_chat_tokens(
            session,
            settings=settings,
            run_id=run_id,
            reservation_key="planner-after-tool-results-abc",
            token_reservation=70,
        )

        event = await session.scalar(
            select(AiUsageEvent).where(AiUsageEvent.run_id == run_id)
        )
        buckets = list((await session.scalars(select(AiUsageBucket))).all())
        assert first is True
        assert duplicate is False
        assert event is not None and event.reserved_tokens == 170
        assert len(buckets) == 3
        assert {bucket.reserved_tokens for bucket in buckets} == {170}

        await settle_chat_tokens(
            session,
            run_id=run_id,
            input_tokens=9,
            output_tokens=4,
        )
        await session.commit()
        assert event.status == "SETTLED"
        assert {bucket.reserved_tokens for bucket in buckets} == {0}
        assert {bucket.used_tokens for bucket in buckets} == {13}


@pytest.mark.asyncio
async def test_additional_planner_reservation_fails_closed_at_user_quota(seeded) -> None:
    factory, college, _, user, *_ = seeded
    settings = Settings(
        environment="test",
        ai_global_daily_token_cap=1000,
        ai_college_daily_token_cap=1000,
        ai_user_daily_token_cap=150,
    )
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="额度不足测试",
            graph_thread_id="quota-reservation-limit",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="quota-reservation-limit",
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            status="RUNNING",
            input_text="查询",
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        await reserve_chat_tokens(
            session,
            settings=settings,
            run_id=run_id,
            user_id=user.id,
            college_id=college.id,
            token_reservation=100,
        )
        await session.commit()

        with pytest.raises(ApiError, match="Token 额度不足") as error:
            await reserve_additional_chat_tokens(
                session,
                settings=settings,
                run_id=run_id,
                reservation_key="over-quota-planner-call",
                token_reservation=100,
            )
        assert getattr(error.value, "code", None) == "AI_DAILY_QUOTA_EXCEEDED"

        event = await session.scalar(
            select(AiUsageEvent).where(AiUsageEvent.run_id == run_id)
        )
        buckets = list((await session.scalars(select(AiUsageBucket))).all())
        assert event is not None and event.reserved_tokens == 100
        assert {bucket.reserved_tokens for bucket in buckets} == {100}


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
        provider="deepseek",
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
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_non_deepseek_chat_provider_does_not_receive_deepseek_options(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    fake_provider = ModuleType("langchain_openai")
    fake_provider.ChatOpenAI = FakeChatOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_provider)

    harness = AgentHarness.__new__(AgentHarness)
    harness.runtime = SimpleNamespace(
        provider="openai-compatible",
        model="test-model",
        api_key="not-a-real-key",
        base_url="https://invalid.example",
    )
    harness.settings = Settings(environment="test", ai_max_output_tokens=321)

    harness._create_chat_model(temperature=0)

    assert "extra_body" not in calls[0]
