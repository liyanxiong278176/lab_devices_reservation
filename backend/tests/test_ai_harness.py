from datetime import UTC, date, datetime, timedelta

import pytest
from app.ai.config import get_runtime_config
from app.ai.graph.harness import AgentHarness, _heuristic_intent
from app.ai.rag.qdrant_store import QdrantKnowledgeStore
from app.api.v2.ai import confirm_ai_action, list_messages
from app.auth.security import Principal, hash_password
from app.core.settings import Settings
from app.infrastructure.db.models import (
    AiConfirmation,
    AiConversation,
    AiMessage,
    AiRun,
    Role,
    User,
)
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select


def test_heuristic_planner_prefers_device_search_for_natural_language_query() -> None:
    intent, arguments = _heuristic_intent("帮我找当前学院空闲的显微镜")

    assert intent == "search_devices"
    assert arguments["query"] == "帮我找当前学院空闲的显微镜"


def test_heuristic_planner_accepts_chinese_calendar_date() -> None:
    intent, arguments = _heuristic_intent("请帮我预约设备1，使用日期为2026年12月10日，用于联调测试")

    assert intent == "create_reservation"
    assert arguments["device_id"] == 1
    assert arguments["start_date"].isoformat() == "2026-12-10"
    assert arguments["end_date"].isoformat() == "2026-12-10"


@pytest.mark.asyncio
async def test_unconfigured_ai_explains_model_configuration(seeded, monkeypatch) -> None:
    factory, _, _, student1, _, _, _, _ = seeded

    async def no_qdrant_search(self, query, college_id, limit=None):
        return []

    async def no_qdrant_close(self):
        return None

    monkeypatch.setattr(QdrantKnowledgeStore, "search", no_qdrant_search)
    monkeypatch.setattr(QdrantKnowledgeStore, "close", no_qdrant_close)

    async with factory() as session:
        conversation = AiConversation(
            user_id=student1.id,
            college_id=student1.college_id,
            title="未配置模型测试",
            graph_thread_id="thread-test-unconfigured",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="run-test-unconfigured",
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            input_text="你好，你是谁",
        )
        session.add(run)
        await session.flush()
        harness = AgentHarness(
            session,
            Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=student1.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id="ai-unconfigured-test",
            ),
            Settings(environment="test", cors_origins=[], enable_workers=False),
            None,
            run,
            conversation.graph_thread_id,
        )
        events = [event async for event in harness.stream()]

    done = next(event for event in events if event["type"] == "done")
    assert done["text"] == (
        "当前 AI 模型尚未配置，暂时无法进行通用对话。"
        "请系统管理员检查后端 .env 中的聊天与 Embedding 配置并重启服务。"
    )


@pytest.mark.asyncio
async def test_langgraph_harness_runs_scoped_read_tool(seeded, monkeypatch) -> None:
    factory, _, _, student1, _, _, _, _ = seeded

    async def no_qdrant_search(self, query, college_id, limit=None):
        return []

    async def no_qdrant_close(self):
        return None

    monkeypatch.setattr(QdrantKnowledgeStore, "search", no_qdrant_search)
    monkeypatch.setattr(QdrantKnowledgeStore, "close", no_qdrant_close)

    async with factory() as session:
        conversation = AiConversation(
            user_id=student1.id,
            college_id=student1.college_id,
            title="测试对话",
            graph_thread_id="thread-test-001",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="run-test-001",
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            input_text="我的预约有哪些？",
        )
        session.add(run)
        await session.flush()
        harness = AgentHarness(
            session,
            Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=student1.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id="ai-test",
            ),
            Settings(environment="test", cors_origins=[], enable_workers=False),
            None,
            run,
            conversation.graph_thread_id,
        )
        events = [event async for event in harness.stream()]

    assert any(event["type"] == "step" for event in events)
    done = next(event for event in events if event["type"] == "done")
    assert done["status"] == "COMPLETED"
    assert "预约" in done["text"]


@pytest.mark.asyncio
async def test_langgraph_write_tool_stops_at_persisted_confirmation(seeded, monkeypatch) -> None:
    factory, _, _, student1, _, _, device, _ = seeded

    async def no_qdrant_search(self, query, college_id, limit=None):
        return []

    async def no_qdrant_close(self):
        return None

    monkeypatch.setattr(QdrantKnowledgeStore, "search", no_qdrant_search)
    monkeypatch.setattr(QdrantKnowledgeStore, "close", no_qdrant_close)
    target = date.today() + timedelta(days=6)

    async with factory() as session:
        conversation = AiConversation(
            user_id=student1.id,
            college_id=student1.college_id,
            title="预约确认测试",
            graph_thread_id="thread-test-confirmation",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="run-test-confirmation",
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            input_text=(
                f"预约设备 {device.id} 在 {target.isoformat()} 到 {target.isoformat()} 用于测试实验"
            ),
        )
        session.add(run)
        await session.flush()
        harness = AgentHarness(
            session,
            Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=student1.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id="ai-confirmation-test",
            ),
            Settings(environment="test", cors_origins=[], enable_workers=False),
            None,
            run,
            conversation.graph_thread_id,
        )
        events = [event async for event in harness.stream()]
        confirmation = await session.scalar(
            select(AiConfirmation).where(AiConfirmation.run_id == run.id)
        )

    done = next(event for event in events if event["type"] == "done")
    assert done["status"] == "WAITING_CONFIRMATION"
    assert confirmation is not None and confirmation.status == "PENDING"


@pytest.mark.asyncio
async def test_ai_provider_runtime_config_comes_only_from_environment(seeded) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        ai_provider="deepseek",
        ai_model="deepseek-flash",
        ai_api_key="environment-chat-key",
        ai_base_url="https://api.deepseek.com",
    )
    async with factory() as session:
        runtime = await get_runtime_config(
            session,
            Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=student1.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id="ai-config-test",
            ),
            settings,
        )

    assert runtime.model == "deepseek-flash"
    assert runtime.api_key == "environment-chat-key"
    assert runtime.base_url == "https://api.deepseek.com"


@pytest.mark.asyncio
async def test_processed_confirmation_is_not_restored_from_history(seeded) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    principal = Principal(
        user_id=student1.id,
        username=student1.username,
        college_id=student1.college_id,
        roles=("STUDENT",),
        token_type="access",
        token_id="confirmation-history-test",
    )
    async with factory() as session:
        conversation = AiConversation(
            user_id=student1.id,
            college_id=student1.college_id,
            title="确认状态恢复测试",
            graph_thread_id="thread-confirmation-history",
        )
        session.add(conversation)
        await session.flush()
        executed_run = AiRun(
            run_key="run-confirmation-executed",
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            input_text="已处理预约",
        )
        pending_run = AiRun(
            run_key="run-confirmation-pending",
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            input_text="待确认预约",
        )
        session.add_all([executed_run, pending_run])
        await session.flush()
        executed = AiConfirmation(
            run_id=executed_run.id,
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            tool_name="create_reservation",
            arguments_json={},
            preview_json={},
            status="EXECUTED",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5),
            result_json={"reservation_id": 1},
        )
        pending = AiConfirmation(
            run_id=pending_run.id,
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            tool_name="create_reservation",
            arguments_json={},
            preview_json={},
            status="PENDING",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5),
        )
        session.add_all([executed, pending])
        await session.flush()
        session.add_all(
            [
                AiMessage(
                    conversation_id=conversation.id,
                    user_id=student1.id,
                    college_id=student1.college_id,
                    role="assistant",
                    content="已处理预览",
                    metadata_json={"pending_confirmation": {"confirmation_id": executed.id}},
                ),
                AiMessage(
                    conversation_id=conversation.id,
                    user_id=student1.id,
                    college_id=student1.college_id,
                    role="assistant",
                    content="待处理预览",
                    metadata_json={"pending_confirmation": {"confirmation_id": pending.id}},
                ),
            ]
        )
        await session.commit()

        response = await list_messages(conversation.id, principal, session)

    assert response.data is not None
    assert "pending_confirmation" not in (response.data[0]["metadata"] or {})
    assert (response.data[1]["metadata"] or {}).get("pending_confirmation") is not None


@pytest.mark.asyncio
async def test_executed_confirmation_is_idempotent(seeded) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    principal = Principal(
        user_id=student1.id,
        username=student1.username,
        college_id=student1.college_id,
        roles=("STUDENT",),
        token_type="access",
        token_id="confirmation-idempotency-test",
    )
    async with factory() as session:
        conversation = AiConversation(
            user_id=student1.id,
            college_id=student1.college_id,
            title="确认幂等测试",
            graph_thread_id="thread-confirmation-idempotency",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="run-confirmation-idempotency",
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            input_text="重复确认",
        )
        session.add(run)
        await session.flush()
        confirmation = AiConfirmation(
            run_id=run.id,
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=student1.college_id,
            tool_name="create_reservation",
            arguments_json={},
            preview_json={},
            status="EXECUTED",
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
            result_json={"reservation_id": 42},
        )
        session.add(confirmation)
        await session.commit()
        confirmation_id = confirmation.id

        response = await confirm_ai_action(confirmation_id, None, principal, session)

    assert response.data is not None
    assert response.data["status"] == "EXECUTED"
    assert response.data["already_processed"] is True
    assert response.data["data"] == {"reservation_id": 42}


@pytest.mark.asyncio
async def test_admin_reads_environment_ai_config_without_persisting_keys(
    seeded, monkeypatch
) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    async with factory() as session:
        admin_role = Role(role_code="SYS_ADMIN", role_name="系统管理员")
        admin = User(
            username="config-admin",
            password_hash=hash_password("config-pass-123"),
            real_name="配置管理员",
            status=1,
            roles=[admin_role],
        )
        session.add_all([admin_role, admin])
        await session.commit()

    settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        jwt_secret="ai-config-test-secret-with-at-least-32-bytes",
        ai_api_key="environment-chat-key",
        ai_embedding_api_key="environment-embedding-key",
        ai_mineru_api_key="environment-mineru-key",
        ai_user_daily_token_cap=1000,
        ai_college_daily_token_cap=10000,
        ai_global_daily_token_cap=100000,
    )

    app = create_app(settings)

    async def successful_provider_test(*_args, **_kwargs):
        from app.ai.providers import ProviderTestResult

        return ProviderTestResult(success=True, message="连接成功", latency_ms=12)

    monkeypatch.setattr("app.api.v2.ai.test_provider", successful_provider_test)

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": "config-admin", "password": "config-pass-123"},
        )
        assert login.status_code == 200
        admin_token = login.json()["data"]["access_token"]
        configs = await client.get(
            "/api/v2/ai/config/components",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert configs.status_code == 200
        config_data = {item["component"]: item for item in configs.json()["data"]}
        assert set(config_data) == {"chat", "embedding", "mineru"}
        for component in config_data.values():
            assert component["source"] == "environment"
            assert component["configured"] is True
            assert component["enabled"] is True
            assert "api_key" not in component
        assert config_data["chat"]["scope"] == "environment"
        assert config_data["chat"]["provider"] == "deepseek"
        assert config_data["chat"]["model"] == "deepseek-flash"
        assert config_data["chat"]["user_daily_token_cap"] == 1000
        assert config_data["chat"]["college_daily_token_cap"] == 10000
        assert config_data["chat"]["global_daily_token_cap"] == 100000
        assert "environment-chat-key" not in configs.text
        assert "environment-embedding-key" not in configs.text
        assert "environment-mineru-key" not in configs.text
        test_result = await client.post(
            "/api/v2/ai/config/chat/test",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={},
        )
        assert test_result.status_code == 200
        assert test_result.json()["data"]["success"] is True
        rejected_write = await client.put(
            "/api/v2/ai/config",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"api_key": "must-not-be-stored"},
        )
        assert rejected_write.status_code == 405
        readiness_response = await client.get(
            "/api/v2/ai/status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert readiness_response.status_code == 200
        assert readiness_response.json()["data"] == {
            "available": True,
            "chat_configured": True,
            "embedding_configured": True,
            "message": "AI 服务已就绪",
        }

    app.dependency_overrides.clear()

    async with factory() as session:
        runtime = await get_runtime_config(
            session,
            Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=student1.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id="global-config-consumer",
            ),
            settings,
        )

    assert runtime is not None
    assert runtime.model == "deepseek-flash"
    assert runtime.api_key == "environment-chat-key"
