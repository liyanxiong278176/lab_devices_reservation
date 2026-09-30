from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dlp import redact_text
from app.infrastructure.db.models import AiContextSnapshot, AiMessage

PROTECTED_TURNS = 5
CONTEXT_SCAN_LIMIT = 2000
SUMMARY_MAX_CHARS = 6000
SUMMARY_LINE_CHARS = 360


@dataclass(frozen=True)
class ConversationContext:
    history: list[dict[str, Any]]
    compressed_summary: str
    protected_message_ids: set[int]


def _compress(messages: list[AiMessage], previous: str) -> str:
    lines = [line for line in previous.splitlines() if line.strip()]
    for message in messages:
        if message.role not in {"user", "assistant"}:
            continue
        prefix = "用户：" if message.role == "user" else "助手："
        safe = redact_text(message.content).text.replace("\n", " ").strip()
        if len(safe) > SUMMARY_LINE_CHARS:
            safe = safe[:SUMMARY_LINE_CHARS].rstrip() + "…（原文仍保存在历史记录中）"
        if safe:
            lines.append(f"{prefix}{safe}")
    return "\n".join(lines)[-SUMMARY_MAX_CHARS:]


async def load_conversation_context(
    session: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    current_run_key: str,
) -> ConversationContext:
    current = datetime.now(UTC).replace(tzinfo=None)
    rows = list(
        (
            await session.scalars(
                select(AiMessage)
                .where(
                    AiMessage.conversation_id == conversation_id,
                    AiMessage.user_id == user_id,
                    AiMessage.archived_at.is_(None),
                    (AiMessage.expires_at.is_(None) | (AiMessage.expires_at > current)),
                )
                .order_by(AiMessage.id.desc())
                .limit(CONTEXT_SCAN_LIMIT)
            )
        ).all()
    )
    rows.reverse()
    current_rows = [
        row
        for row in rows
        if isinstance(row.metadata_json, dict)
        and row.metadata_json.get("run_key") == current_run_key
    ]
    current_ids = {row.id for row in current_rows}
    prior_rows = [row for row in rows if row.id not in current_ids]
    user_turn_indexes = [index for index, row in enumerate(prior_rows) if row.role == "user"]
    if len(user_turn_indexes) > PROTECTED_TURNS:
        protected_start = user_turn_indexes[-PROTECTED_TURNS]
    else:
        protected_start = 0
    older = prior_rows[:protected_start]
    protected = prior_rows[protected_start:]

    snapshot = await session.scalar(
        select(AiContextSnapshot)
        .where(
            AiContextSnapshot.conversation_id == conversation_id,
            AiContextSnapshot.user_id == user_id,
        )
    )
    older_ids = [row.id for row in older]
    active_ids = {row.id for row in rows}
    if snapshot is not None and not set(snapshot.source_message_ids or []).issubset(active_ids):
        # A compressed snapshot is derived L0 data. Do not keep expired or
        # archived text alive through the summary after the raw item ages out.
        snapshot.summary = ""
        snapshot.source_message_ids = []
        snapshot.through_message_id = 0
        snapshot.version += 1
        await session.flush()
    new_older = [row for row in older if snapshot is None or row.id > snapshot.through_message_id]
    if new_older:
        previous = snapshot.summary if snapshot is not None else ""
        summary = _compress(new_older, previous)
        through_id = max(row.id for row in new_older)
        prior_ids = snapshot.source_message_ids if snapshot is not None else []
        source_ids = list(dict.fromkeys([*prior_ids, *older_ids]))[-5000:]
        if snapshot is None:
            snapshot = AiContextSnapshot(
                conversation_id=conversation_id,
                user_id=user_id,
                summary=summary,
                source_message_ids=source_ids,
                through_message_id=through_id,
                version=1,
            )
            session.add(snapshot)
        elif through_id > snapshot.through_message_id:
            snapshot.summary = summary
            snapshot.source_message_ids = source_ids
            snapshot.through_message_id = through_id
            snapshot.version += 1
        await session.flush()

    summary_text = snapshot.summary if snapshot is not None else ""
    history = [
        {
            "role": row.role,
            "content": redact_text(row.content).text,
            "metadata": row.metadata_json or {},
        }
        for row in protected
        if row.role in {"user", "assistant", "tool"}
    ]
    return ConversationContext(
        history=history,
        compressed_summary=summary_text,
        protected_message_ids={row.id for row in protected} | current_ids,
    )
