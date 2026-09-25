from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.db.models import AiCheckpoint, AiCheckpointWrite


class MySQLCheckpointSaver(BaseCheckpointSaver):
    """Async LangGraph checkpointer backed by the application's MySQL database."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        super().__init__()
        self.session_factory = session_factory

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        del new_versions  # The full typed checkpoint is stored atomically as one blob.
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        namespace = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = str(checkpoint["id"])
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        normalized_metadata = get_checkpoint_metadata(config, metadata)
        metadata_type, metadata_blob = self.serde.dumps_typed(normalized_metadata)
        async with self.session_factory() as session, session.begin():
            session.add(
                AiCheckpoint(
                    thread_id=thread_id,
                    checkpoint_ns=namespace,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=configurable.get("checkpoint_id"),
                    checkpoint_type=checkpoint_type,
                    checkpoint_blob=checkpoint_blob,
                    metadata_type=metadata_type,
                    metadata_blob=metadata_blob,
                )
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        namespace = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = str(configurable["checkpoint_id"])
        async with self.session_factory() as session, session.begin():
            for index, (channel, value) in enumerate(writes):
                write_index = WRITES_IDX_MAP.get(channel, index)
                value_type, value_blob = self.serde.dumps_typed(value)
                existing = await session.scalar(
                    select(AiCheckpointWrite.id).where(
                        AiCheckpointWrite.thread_id == thread_id,
                        AiCheckpointWrite.checkpoint_ns == namespace,
                        AiCheckpointWrite.checkpoint_id == checkpoint_id,
                        AiCheckpointWrite.task_id == task_id,
                        AiCheckpointWrite.write_index == write_index,
                    )
                )
                if existing is None:
                    session.add(
                        AiCheckpointWrite(
                            thread_id=thread_id,
                            checkpoint_ns=namespace,
                            checkpoint_id=checkpoint_id,
                            task_id=task_id,
                            write_index=write_index,
                            channel=channel,
                            value_type=value_type,
                            value_blob=value_blob,
                            task_path=task_path,
                        )
                    )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        namespace = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = get_checkpoint_id(config)
        async with self.session_factory() as session:
            statement = select(AiCheckpoint).where(
                AiCheckpoint.thread_id == thread_id,
                AiCheckpoint.checkpoint_ns == namespace,
            )
            if checkpoint_id:
                statement = statement.where(AiCheckpoint.checkpoint_id == checkpoint_id)
            else:
                statement = statement.order_by(AiCheckpoint.id.desc()).limit(1)
            row = await session.scalar(statement)
            if row is None:
                return None
            writes = list(
                (
                    await session.scalars(
                        select(AiCheckpointWrite)
                        .where(
                            AiCheckpointWrite.thread_id == thread_id,
                            AiCheckpointWrite.checkpoint_ns == namespace,
                            AiCheckpointWrite.checkpoint_id == row.checkpoint_id,
                        )
                        .order_by(AiCheckpointWrite.id)
                    )
                ).all()
            )
            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": namespace,
                        "checkpoint_id": row.checkpoint_id,
                    }
                },
                checkpoint=self.serde.loads_typed((row.checkpoint_type, row.checkpoint_blob)),
                metadata=self.serde.loads_typed((row.metadata_type, row.metadata_blob)),
                pending_writes=[
                    (
                        item.task_id,
                        item.channel,
                        self.serde.loads_typed((item.value_type, item.value_blob)),
                    )
                    for item in writes
                ],
                parent_config=(
                    {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": namespace,
                            "checkpoint_id": row.parent_checkpoint_id,
                        }
                    }
                    if row.parent_checkpoint_id
                    else None
                ),
            )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        del filter
        async with self.session_factory() as session:
            statement = select(AiCheckpoint).order_by(AiCheckpoint.id.desc())
            if config is not None:
                configurable = config["configurable"]
                statement = statement.where(
                    AiCheckpoint.thread_id == str(configurable["thread_id"]),
                    AiCheckpoint.checkpoint_ns == str(configurable.get("checkpoint_ns", "")),
                )
            if before is not None:
                before_id = get_checkpoint_id(before)
                if before_id:
                    before_configurable = before["configurable"]
                    before_row = await session.scalar(
                        select(AiCheckpoint.id).where(
                            AiCheckpoint.thread_id == str(before_configurable["thread_id"]),
                            AiCheckpoint.checkpoint_ns
                            == str(before_configurable.get("checkpoint_ns", "")),
                            AiCheckpoint.checkpoint_id == before_id,
                        )
                    )
                    if before_row is not None:
                        statement = statement.where(AiCheckpoint.id < before_row)
            if limit is not None:
                statement = statement.limit(limit)
            rows = list((await session.scalars(statement)).all())
            tuples: list[CheckpointTuple] = []
            for row in rows:
                checkpoint_config = {
                    "configurable": {
                        "thread_id": row.thread_id,
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.checkpoint_id,
                    }
                }
                tuples.append(
                    CheckpointTuple(
                        config=checkpoint_config,
                        checkpoint=self.serde.loads_typed(
                            (row.checkpoint_type, row.checkpoint_blob)
                        ),
                        metadata=self.serde.loads_typed((row.metadata_type, row.metadata_blob)),
                        parent_config=(
                            {
                                "configurable": {
                                    "thread_id": row.thread_id,
                                    "checkpoint_ns": row.checkpoint_ns,
                                    "checkpoint_id": row.parent_checkpoint_id,
                                }
                            }
                            if row.parent_checkpoint_id
                            else None
                        ),
                    )
                )
        for item in tuples:
            yield item

    async def adelete_thread(self, thread_id: str) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(
                delete(AiCheckpointWrite).where(AiCheckpointWrite.thread_id == thread_id)
            )
            await session.execute(delete(AiCheckpoint).where(AiCheckpoint.thread_id == thread_id))
