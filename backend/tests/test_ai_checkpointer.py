import pytest
from app.ai.graph.mysql_checkpointer import MySQLCheckpointSaver
from app.infrastructure.db.models import AiCheckpoint, AiCheckpointWrite
from sqlalchemy import select


@pytest.mark.asyncio
async def test_mysql_checkpoint_round_trip_and_idempotent_task_writes(session_factory) -> None:
    saver = MySQLCheckpointSaver(session_factory)
    config = {"configurable": {"thread_id": "checkpoint-test", "checkpoint_ns": ""}}
    checkpoint = {
        "v": 1,
        "id": "checkpoint-1",
        "ts": "2026-09-27T10:00:00+00:00",
        "channel_values": {"phase": "retrieved", "input_text": "预约设备"},
        "channel_versions": {"phase": 1, "input_text": 1},
        "versions_seen": {},
        "pending_sends": [],
    }
    metadata = {"source": "loop", "step": 2, "parents": {}}

    saved_config = await saver.aput(config, checkpoint, metadata, {})
    await saver.aput_writes(saved_config, [("tool_result", {"ok": True})], "task-1")
    await saver.aput_writes(saved_config, [("tool_result", {"ok": True})], "task-1")
    restored = await saver.aget_tuple(saved_config)

    assert restored is not None
    assert restored.checkpoint["channel_values"] == checkpoint["channel_values"]
    assert restored.metadata["step"] == 2
    assert len(restored.pending_writes) == 1
    async with session_factory() as session:
        assert len(list((await session.scalars(select(AiCheckpoint))).all())) == 1
        assert len(list((await session.scalars(select(AiCheckpointWrite))).all())) == 1
