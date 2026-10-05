from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.ai.config import get_runtime_config
from app.ai.graph.harness import (
    AgentHarness,
    PlanDecision,
    TokenUsageAccumulator,
    _canonical_hash,
    _fallback_standalone_query,
    _forced_availability_followup,
    _forced_quoted_device_search,
    _graph_start_state,
    _heuristic_intent,
)
from app.ai.rag.qdrant_store import QdrantKnowledgeStore
from app.ai.runtime import execute_ai_run
from app.ai.tools.registry import AvailabilityInput, SearchDevicesInput
from app.api.v2.ai import confirm_ai_action, list_messages
from app.auth.security import Principal, hash_password
from app.core.settings import Settings
from app.infrastructure.db.models import (
    AiConfirmation,
    AiContextSnapshot,
    AiConversation,
    AiMemory,
    AiMessage,
    AiRun,
    AiRunEvent,
    AiToolExecution,
    Role,
    User,
)
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from langchain_core.runnables import RunnableLambda
from sqlalchemy import select
from sqlalchemy.orm import selectinload


class CountingTool:
    args_schema = SearchDevicesInput

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, arguments):
        self.calls += 1
        return {"items": [{"id": 11, "name": arguments.get("query", "device")}]}


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
async def test_invalid_llm_tool_arguments_fall_back_to_typed_domain_parser(monkeypatch) -> None:
    class FakeModel:
        def with_structured_output(self, schema, *, method):
            assert schema is PlanDecision
            assert method == "function_calling"
            return RunnableLambda(
                lambda _: PlanDecision(
                    intent="check_availability",
                    arguments={"device_id": "6", "date": "2026-10-04"},
                )
            )

    harness = AgentHarness.__new__(AgentHarness)
    harness.runtime = SimpleNamespace(api_key="test-runtime-key")
    harness.tools = {"check_availability": SimpleNamespace(args_schema=AvailabilityInput)}
    harness.usage = TokenUsageAccumulator()
    monkeypatch.setattr(harness, "_create_chat_model", lambda **_: FakeModel())

    plan = await harness._plan_node(
        {"input_text": "请查询设备6在2026-10-04是否可用", "sources": []}
    )

    assert plan["intent"] == "check_availability"
    assert plan["tool_arguments"] == {
        "device_id": 6,
        "start_date": "2026-10-04",
        "end_date": "2026-10-04",
    }


@pytest.mark.asyncio
async def test_valid_llm_tool_arguments_are_normalized_before_execution(monkeypatch) -> None:
    class FakeModel:
        def with_structured_output(self, schema, *, method):
            del schema, method
            return RunnableLambda(
                lambda _: PlanDecision(
                    intent="check_availability",
                    arguments={
                        "device_id": "6",
                        "start_date": "2026-10-04",
                        "end_date": "2026-10-04",
                    },
                )
            )

    harness = AgentHarness.__new__(AgentHarness)
    harness.runtime = SimpleNamespace(api_key="test-runtime-key")
    harness.tools = {"check_availability": SimpleNamespace(args_schema=AvailabilityInput)}
    harness.usage = TokenUsageAccumulator()
    monkeypatch.setattr(harness, "_create_chat_model", lambda **_: FakeModel())

    decision = await harness._llm_plan("请查询设备6在2026-10-04是否可用", [])

    assert decision is not None
    assert decision.arguments == {
        "device_id": 6,
        "start_date": "2026-10-04",
        "end_date": "2026-10-04",
    }


@pytest.mark.asyncio
async def test_followup_planner_uses_resolved_device_and_date_context() -> None:
    harness = AgentHarness.__new__(AgentHarness)
    harness.runtime = SimpleNamespace(api_key=None)

    planned = await harness._plan_node(
        {
            "input_text": "帮我预约它",
            "standalone_query": "请帮我预约设备6，使用日期为2026-10-04",
            "sources": [],
            "steps": [],
        }
    )

    assert planned["intent"] == "create_reservation"
    assert planned["tool_arguments"]["device_id"] == 6
    assert planned["tool_arguments"]["start_date"] == "2026-10-04"


@pytest.mark.asyncio
async def test_explicit_first_search_result_availability_followup_is_deterministic() -> None:
    harness = AgentHarness.__new__(AgentHarness)
    search_result = {
        "items": [
            {"id": 18, "name": "电子显微镜"},
            {"id": 19, "name": "扫描显微镜"},
        ]
    }
    state = {
        "input_text": "先搜索显微镜，再选择搜索结果中的第一台设备，查询它在2026-10-04是否可用。",
        "standalone_query": "搜索显微镜并查询第一台设备 2026-10-04 可用性",
        "sources": [],
        "steps": [],
        "tool_history": [
            {
                "intent": "search_devices",
                "arguments": {"query": "显微镜"},
                "result": search_result,
                "signature": _canonical_hash(
                    {"intent": "search_devices", "arguments": {"query": "显微镜"}}
                ),
                "progress_hash": _canonical_hash(search_result),
                "attempt": 1,
                "tool_call_id": "first-search",
            }
        ],
    }

    assert _forced_availability_followup(state) == {
        "device_id": 18,
        "start_date": "2026-10-04",
        "end_date": "2026-10-04",
    }
    plan = await harness._plan_node(state)
    assert plan["intent"] == "check_availability"
    assert plan["tool_arguments"]["device_id"] == 18
    assert plan["tool_arguments"]["start_date"] == "2026-10-04"

    already_checked = {
        **state,
        "tool_history": [
            *state["tool_history"],
            {
                "intent": "check_availability",
                "arguments": {
                    "device_id": 18,
                    "start_date": "2026-10-04",
                    "end_date": "2026-10-04",
                },
                "result": {"days": []},
            },
        ],
    }
    assert _forced_availability_followup(already_checked) is None
    assert await harness._plan_node(already_checked) == {
        "intent": "answer",
        "tool_arguments": {},
        "steps": [{"name": "policy_planner", "status": "completed", "intent": "answer"}],
    }


def test_explicit_quoted_device_search_uses_the_quoted_term() -> None:
    question = "请先搜索名称包含“显微镜”的设备，再检查第一台的日期可用性。"

    assert _forced_quoted_device_search({"input_text": question, "tool_history": []}) == "显微镜"
    assert _forced_quoted_device_search(
        {"input_text": question, "tool_history": [{"intent": "search_devices"}]}
    ) is None


@pytest.mark.asyncio
async def test_planner_allows_one_identical_read_retry_then_stops_no_progress() -> None:
    harness = AgentHarness.__new__(AgentHarness)
    harness.runtime = SimpleNamespace(api_key=None)
    calls = 0
    arguments = {"query": "显微镜"}
    signature = _canonical_hash({"intent": "search_devices", "arguments": arguments})
    progress_hash = _canonical_hash({"items": [{"id": 11, "name": "显微镜"}]})

    async def repeat_same_plan(_question, _sources, *, tool_history):
        nonlocal calls
        calls += 1
        return PlanDecision(intent="search_devices", arguments=arguments)

    harness._llm_plan = repeat_same_plan
    one_result = {
        "intent": "search_devices",
        "arguments": arguments,
        "signature": signature,
        "progress_hash": progress_hash,
        "attempt": 1,
        "tool_call_id": "tool-call-1",
        "result": {"items": [{"id": 11, "name": "显微镜"}]},
    }
    two_same_results = [
        one_result,
        {**one_result, "attempt": 2, "tool_call_id": "tool-call-2"},
    ]

    retry = await harness._plan_node(
        {
            "input_text": "查询显微镜",
            "sources": [],
            "tool_history": [one_result],
            "steps": [],
        }
    )
    stopped = await harness._plan_node(
        {
            "input_text": "查询显微镜",
            "sources": [],
            "tool_history": two_same_results,
            "steps": [],
        }
    )
    stopped_after_changed_result = await harness._plan_node(
        {
            "input_text": "查询显微镜",
            "sources": [],
            "tool_history": [
                one_result,
                {
                    **one_result,
                    "attempt": 2,
                    "tool_call_id": "tool-call-2",
                    "result": {"items": [{"id": 12, "name": "另一台显微镜"}]},
                    "progress_hash": _canonical_hash(
                        {"items": [{"id": 12, "name": "另一台显微镜"}]}
                    ),
                },
            ],
            "steps": [],
        }
    )

    assert retry["intent"] == "search_devices"
    assert stopped["intent"] == "answer"
    assert stopped["no_progress"] is True
    assert stopped_after_changed_result["intent"] == "answer"
    assert stopped_after_changed_result["read_retry_exhausted"] is True
    assert calls == 3


@pytest.mark.asyncio
async def test_graph_runs_multiple_read_tools_before_answer() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    harness = AgentHarness.__new__(AgentHarness)
    harness.checkpointer = MemorySaver()
    calls: list[str] = []
    planned = iter(["search_devices", "check_availability", "answer"])

    async def rewrite(state):
        return {"standalone_query": state["input_text"], "search_queries": []}

    async def retrieve(_state):
        return {"sources": []}

    async def plan(_state):
        intent = next(planned)
        calls.append(f"plan:{intent}")
        return {
            "intent": intent,
            "tool_arguments": {"query": "显微镜"} if intent == "search_devices" else {},
        }

    async def tool(state):
        intent = state["intent"]
        calls.append(f"tool:{intent}")
        entry = {
            "intent": intent,
            "arguments": state.get("tool_arguments", {}),
            "signature": _canonical_hash(
                {"intent": intent, "arguments": state.get("tool_arguments", {})}
            ),
            "tool_call_id": f"fake-{len(calls)}",
            "attempt": 1,
            "result": {"items": []} if intent == "search_devices" else {"days": []},
            "progress_hash": _canonical_hash({"result": len(calls)}),
        }
        return {
            "tool_result": entry["result"],
            "tool_history": [*state.get("tool_history", []), entry],
        }

    async def unused(_state):
        return {}

    async def answer(_state):
        calls.append("answer")
        return {"answer": "查询完成"}

    harness._query_rewrite_node = rewrite
    harness._retrieve_node = retrieve
    harness._plan_node = plan
    harness._tool_node = tool
    harness._forget_memory_node = unused
    harness._answer_node = answer
    result = await harness._build_graph().ainvoke(
        {"input_text": "查设备并检查日期", "steps": []},
        config={"configurable": {"thread_id": "multi-read-tools"}, "recursion_limit": 100},
    )

    assert result["answer"] == "查询完成"
    assert calls == [
        "plan:search_devices",
        "tool:search_devices",
        "plan:check_availability",
        "tool:check_availability",
        "plan:answer",
        "answer",
    ]


def test_planner_receives_tool_results_as_non_system_message_context() -> None:
    from langchain_core.messages import HumanMessage

    messages = AgentHarness._planner_tool_messages(
        [
            {
                "intent": "search_devices",
                "arguments": {"query": "显微镜"},
                "tool_call_id": "tool-search-1",
                "result": {"items": [{"id": 11}]},
            }
        ]
    )

    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert "search_devices" in messages[0].content
    assert '"id": 11' in messages[0].content


def test_final_answer_combines_distinct_tool_results_and_citations() -> None:
    harness = AgentHarness.__new__(AgentHarness)
    harness.principal = SimpleNamespace(college_id=3)
    search_arguments = {"query": "显微镜"}
    availability_arguments = {
        "device_id": 6,
        "start_date": "2026-10-04",
        "end_date": "2026-10-04",
    }
    search_signature = _canonical_hash(
        {"intent": "search_devices", "arguments": search_arguments}
    )
    availability_signature = _canonical_hash(
        {"intent": "check_availability", "arguments": availability_arguments}
    )
    search_result = {
        "total": 1,
        "items": [{"id": 6, "name": "电子显微镜", "asset_code": "EM-006"}],
    }
    availability_result = {
        "days": [{"date": "2026-10-04", "available": True}],
    }
    history = [
        {
            "intent": "search_devices",
            "arguments": search_arguments,
            "signature": search_signature,
            "tool_call_id": "search-call",
            "attempt": 1,
            "result": search_result,
            "progress_hash": _canonical_hash(search_result),
        },
        {
            "intent": "check_availability",
            "arguments": availability_arguments,
            "signature": availability_signature,
            "tool_call_id": "availability-call",
            "attempt": 1,
            "result": availability_result,
            "progress_hash": _canonical_hash(availability_result),
        },
    ]

    answer, citations = harness._answer_from_tool_history(
        {"tool_history": history, "no_progress": True}
    )

    assert "重复读取未带来新结果" in answer
    assert "电子显微镜（EM-006）" in answer
    assert "2026-10-04" in answer and "可用日期" in answer
    assert {item["entity"] for item in citations} == {"device", "availability"}
    assert answer.count("[citation:") == 2


@pytest.mark.asyncio
async def test_graph_resume_uses_saved_checkpoint_without_replaying_completed_node() -> None:
    calls: list[str] = []
    harness = AgentHarness.__new__(AgentHarness)
    from langgraph.checkpoint.memory import MemorySaver

    harness.checkpointer = MemorySaver()

    async def rewrite(state):
        calls.append("rewrite")
        return {
            "search_queries": [state["input_text"]],
            "standalone_query": state["input_text"],
        }

    async def retrieve(state):
        calls.append("retrieve")
        return {"sources": []}

    async def plan(_state):
        return {"intent": "answer"}

    async def answer(_state):
        return {"answer": "ok"}

    async def unused(_state):
        return {}

    harness._query_rewrite_node = rewrite
    harness._retrieve_node = retrieve
    harness._plan_node = plan
    harness._answer_node = answer
    harness._tool_node = unused
    harness._forget_memory_node = unused
    graph = harness._build_graph()
    config = {"configurable": {"thread_id": "resume-regression"}}
    initial = {"input_text": "设备6可用吗", "steps": []}

    await graph.ainvoke(initial, config, interrupt_after=["rewrite"])
    resumed_input, restored_state = await _graph_start_state(graph, config, initial)
    assert resumed_input is None
    assert restored_state["standalone_query"] == "设备6可用吗"
    assert restored_state["search_queries"] == ["设备6可用吗"]
    await graph.ainvoke(resumed_input, config)

    assert calls == ["rewrite", "retrieve"]


@pytest.mark.asyncio
async def test_queued_run_is_rejected_if_ai_permission_is_revoked(seeded) -> None:
    factory, _, _, student, *_ = seeded
    async with factory() as session:
        student = await session.scalar(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.id == student.id)
        )
        assert student is not None
        student.roles[0].permissions.clear()
        conversation = AiConversation(
            user_id=student.id,
            college_id=student.college_id,
            title="授权变更后运行",
            graph_thread_id="thread-ai-permission-revoked",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="run-ai-permission-revoked",
            conversation_id=conversation.id,
            user_id=student.id,
            college_id=student.college_id,
            status="QUEUED",
            input_text="查询设备",
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()

    app = SimpleNamespace(
        state=SimpleNamespace(
            ai_run_tasks={},
            session_factory=factory,
            settings=Settings(environment="test"),
        )
    )
    await execute_ai_run(app, run_id)

    async with factory() as session:
        run = await session.get(AiRun, run_id)
        event = await session.scalar(
            select(AiRunEvent).where(AiRunEvent.run_id == run_id)
        )
    assert run is not None and run.status == "FAILED"
    assert run.error_code == "AI_PERMISSION_REVOKED"
    assert event is not None and event.payload["code"] == "AI_PERMISSION_REVOKED"


def test_vague_followup_rewrite_retains_raw_query_and_prior_topic() -> None:
    history = [
        {"role": "user", "content": "显微镜的预约规则是什么"},
        {"role": "assistant", "content": "请查看预约规则说明"},
    ]
    standalone = _fallback_standalone_query("那这个呢？", history)

    assert "显微镜的预约规则是什么" in standalone
    assert "那这个呢？" in standalone


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
        "请系统管理员检查根目录 .env 中的聊天与 Embedding 配置并重启服务。"
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
                    permissions=("reservation:read:own",),
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
                permissions=("device:read", "reservation:create"),
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
async def test_forget_confirmation_invalidates_only_owner_memory_and_snapshot(seeded) -> None:
    factory, college, other_college, student1, student2, *_ = seeded
    now = datetime.now(UTC).replace(tzinfo=None)
    principal = Principal(
        user_id=student1.id,
        username=student1.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="forget-memory-confirmation",
        permissions=("ai:use",),
    )
    async with factory() as session:
        conversation = AiConversation(
            user_id=student1.id,
            college_id=college.id,
            title="记忆删除测试",
            graph_thread_id="thread-forget-confirmation",
        )
        other_conversation = AiConversation(
            user_id=student2.id,
            college_id=other_college.id,
            title="他人记忆",
            graph_thread_id="thread-forget-confirmation-other",
        )
        session.add_all([conversation, other_conversation])
        await session.flush()
        run = AiRun(
            run_key="run-forget-confirmation",
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=college.id,
            status="WAITING_CONFIRMATION",
            input_text="忘记显微镜预约记忆",
        )
        session.add(run)
        await session.flush()
        raw_message = AiMessage(
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=college.id,
            role="user",
            content="我负责显微镜预约相关项目",
        )
        own_memory = AiMemory(
            user_id=student1.id,
            college_id=college.id,
            level="L1",
            scenario="reservation",
            content="我负责显微镜预约相关项目",
            source_message_ids=[],
            source_run_ids=[run.id],
            status="ACTIVE",
            expires_at=now + timedelta(days=180),
        )
        foreign_memory = AiMemory(
            user_id=student2.id,
            college_id=other_college.id,
            level="L1",
            scenario="reservation",
            content="我负责显微镜预约相关项目",
            source_message_ids=[],
            source_run_ids=[],
            status="ACTIVE",
            expires_at=now + timedelta(days=180),
        )
        session.add_all([raw_message, own_memory, foreign_memory])
        await session.flush()
        own_memory.source_message_ids = [raw_message.id]
        snapshot = AiContextSnapshot(
            conversation_id=conversation.id,
            user_id=student1.id,
            summary="用户负责显微镜预约相关项目",
            source_message_ids=[raw_message.id],
            through_message_id=raw_message.id,
        )
        session.add(snapshot)
        confirmation = AiConfirmation(
            run_id=run.id,
            conversation_id=conversation.id,
            user_id=student1.id,
            college_id=college.id,
            tool_name="forget_ai_memories",
            arguments_json={
                "memory_ids": [own_memory.id],
                "source_message_ids": [raw_message.id],
                "topic": "显微镜预约",
            },
            preview_json={
                "topic": "显微镜预约",
                "matches": [
                    {
                        "id": own_memory.id,
                        "level": "L1",
                        "scenario": "reservation",
                        "content": own_memory.content,
                    }
                ],
            },
            status="PENDING",
            idempotency_key="forget-confirmation-test",
            expires_at=now + timedelta(minutes=10),
        )
        session.add(confirmation)
        await session.commit()
        confirmation_id = confirmation.id
        raw_message_id = raw_message.id
        own_memory_id = own_memory.id
        foreign_memory_id = foreign_memory.id

        response = await confirm_ai_action(confirmation_id, None, principal, session)

        assert response.data["status"] == "EXECUTED"
        assert response.data["data"] == {
            "forgotten_count": 1,
            "raw_conversation_preserved": True,
        }
        assert (await session.get(AiMemory, own_memory_id)).status == "INVALID"
        assert (await session.get(AiMemory, foreign_memory_id)).status == "ACTIVE"
        assert await session.get(AiContextSnapshot, snapshot.id) is None
        assert await session.get(AiMessage, raw_message_id) is not None
        refreshed_run = await session.get(AiRun, run.id)
        assert refreshed_run.status == "COMPLETED"
        assert "原始对话仍保留" in refreshed_run.output_text


@pytest.mark.asyncio
async def test_tool_replay_uses_durable_result_without_second_invocation(seeded) -> None:
    factory, college, _, user, *_ = seeded
    principal = Principal(
        user_id=user.id,
        username=user.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="ai-tool-idempotency",
        permissions=("device:read",),
    )
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="工具幂等测试",
            graph_thread_id="thread-tool-idempotency",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="run-tool-idempotency",
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            input_text="查询设备",
        )
        session.add(run)
        await session.flush()
        harness = AgentHarness(
            session,
            principal,
            Settings(environment="test", cors_origins=[], enable_workers=False),
            None,
            run,
            conversation.graph_thread_id,
        )
        tool = CountingTool()
        harness.tools["search_devices"] = tool
        state = {
            "intent": "search_devices",
            "tool_arguments": {"query": "显微镜"},
            "steps": [],
        }

        first = await harness._tool_node(state)
        second = await harness._tool_node(state)
        ledger_rows = list((await session.scalars(select(AiToolExecution))).all())
        tool_messages = list(
            (
                await session.scalars(
                    select(AiMessage).where(
                        AiMessage.conversation_id == conversation.id,
                        AiMessage.role == "tool",
                    )
                )
            ).all()
        )

    assert tool.calls == 1
    assert first["tool_result"] == second["tool_result"]
    assert len(ledger_rows) == 1 and ledger_rows[0].status == "COMPLETED"
    assert len(tool_messages) == 1
    assert tool_messages[0].metadata_json["tool_name"] == "search_devices"


@pytest.mark.asyncio
async def test_identical_read_retry_uses_distinct_idempotency_key_and_persists_history(
    seeded,
) -> None:
    factory, college, _, user, *_ = seeded
    principal = Principal(
        user_id=user.id,
        username=user.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="ai-tool-identical-retry",
        permissions=("device:read",),
    )
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="只读工具重试",
            graph_thread_id="thread-tool-identical-retry",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="run-tool-identical-retry",
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            input_text="查询显微镜",
        )
        session.add(run)
        await session.flush()
        harness = AgentHarness(
            session,
            principal,
            Settings(environment="test", cors_origins=[], enable_workers=False),
            None,
            run,
            conversation.graph_thread_id,
        )
        tool = CountingTool()
        harness.tools["search_devices"] = tool
        state = {
            "intent": "search_devices",
            "tool_arguments": {"query": "显微镜"},
            "steps": [],
        }

        first = await harness._tool_node(state)
        second = await harness._tool_node(
            {**state, "tool_history": first["tool_history"]}
        )
        ledgers = list(
            (
                await session.scalars(
                    select(AiToolExecution).where(AiToolExecution.run_id == run.id)
                )
            ).all()
        )
        tool_messages = list(
            (
                await session.scalars(
                    select(AiMessage).where(
                        AiMessage.conversation_id == conversation.id,
                        AiMessage.role == "tool",
                    )
                )
            ).all()
        )

    assert tool.calls == 2
    assert first["tool_call_id"] != second["tool_call_id"]
    assert second["tool_call_id"].endswith("-retry-1")
    assert len(ledgers) == 2
    assert len(tool_messages) == 2
    assert len(second["tool_history"]) == 2
    assert first["tool_history"][0]["progress_hash"] == second["tool_history"][1][
        "progress_hash"
    ]


@pytest.mark.asyncio
async def test_uncertain_started_tool_is_never_replayed_automatically(seeded) -> None:
    factory, college, _, user, *_ = seeded
    principal = Principal(
        user_id=user.id,
        username=user.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="ai-tool-outcome-unknown",
        permissions=("device:read",),
    )
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="工具中断测试",
            graph_thread_id="thread-tool-outcome-unknown",
        )
        session.add(conversation)
        await session.flush()
        run = AiRun(
            run_key="run-tool-outcome-unknown",
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            input_text="查询设备",
        )
        session.add(run)
        await session.flush()
        args = {"query": "显微镜"}
        args_hash = _canonical_hash(args)
        call_id = f"run-{run.id}-search_devices-{args_hash[:12]}"
        idempotency_key = _canonical_hash(
            {"run_id": run.id, "tool_call_id": call_id, "arguments_hash": args_hash}
        )
        session.add(
            AiToolExecution(
                run_id=run.id,
                user_id=user.id,
                college_id=college.id,
                tool_name="search_devices",
                tool_call_id=call_id,
                idempotency_key=idempotency_key,
                arguments_hash=args_hash,
                arguments_json=args,
                status="STARTED",
            )
        )
        await session.flush()
        harness = AgentHarness(
            session,
            principal,
            Settings(environment="test", cors_origins=[], enable_workers=False),
            None,
            run,
            conversation.graph_thread_id,
        )
        tool = CountingTool()
        harness.tools["search_devices"] = tool
        result = await harness._tool_node(
            {"intent": "search_devices", "tool_arguments": args, "steps": []}
        )

    assert tool.calls == 0
    assert result["tool_result"]["code"] == "AI_TOOL_OUTCOME_UNKNOWN"


@pytest.mark.asyncio
async def test_admin_reads_environment_ai_config_without_persisting_keys(
    seeded, monkeypatch
) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    async with factory() as session:
        admin_role = await session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
        assert admin_role is not None
        admin = User(
            username="config-admin",
            password_hash=hash_password("config-pass-123"),
            real_name="配置管理员",
            status=1,
            roles=[admin_role],
        )
        session.add(admin)
        await session.commit()

    settings = Settings(
        environment="test",
        cors_origins=["http://test"],
        redis_url="redis://127.0.0.1:6379/15",
        enable_workers=False,
        rate_limit_enabled=False,
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
        csrf_response = await client.get("/api/v2/auth/csrf")
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": "config-admin", "password": "config-pass-123"},
            headers={
                "Origin": "http://test",
                "X-CSRF-Token": csrf_response.json()["data"]["csrf_token"],
            },
        )
        assert login.status_code == 200
        admin_headers = {
            "Origin": "http://test",
            "X-CSRF-Token": login.json()["data"]["csrf_token"],
        }
        configs = await client.get(
            "/api/v2/ai/config/components",
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
            headers=admin_headers,
            json={},
        )
        assert test_result.status_code == 200
        assert test_result.json()["data"]["success"] is True
        rejected_write = await client.put(
            "/api/v2/ai/config",
            headers=admin_headers,
            json={"api_key": "must-not-be-stored"},
        )
        assert rejected_write.status_code == 405
        readiness_response = await client.get(
            "/api/v2/ai/status",
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
