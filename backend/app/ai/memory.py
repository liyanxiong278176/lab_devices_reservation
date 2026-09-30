from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dlp import redact_text
from app.infrastructure.db.models import AiMemory, AiMemoryRecall, AiMessage, AiMessageRecall

INITIAL_TTL_DAYS = 180
MAX_TTL_DAYS = 360
ARCHIVE_GRACE_DAYS = 180


@dataclass(frozen=True)
class MemoryCandidate:
    level: str
    scenario: str
    content: str


def memory_ttl_days(valid_recall_count: int) -> float:
    count = max(0, valid_recall_count)
    return min(MAX_TTL_DAYS, INITIAL_TTL_DAYS + 60 * math.log2(1 + count))


def _terms(text: str) -> set[str]:
    parts = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.casefold())
    output: set[str] = set()
    for part in parts:
        if len(part) <= 2:
            output.add(part)
        else:
            output.update(part[index : index + 2] for index in range(len(part) - 1))
    return {item for item in output if len(item) > 1}


def _relevance(query: str, content: str) -> float:
    query_terms = _terms(query)
    content_terms = _terms(content)
    if not query_terms or not content_terms:
        return 0.0
    return len(query_terms & content_terms) / len(query_terms)


def _scenario(text: str) -> str:
    for scenario, terms in (
        ("reservation", ("预约", "借用", "设备")),
        ("repair", ("报修", "故障", "维修")),
        ("maintenance", ("校准", "保养", "维护")),
        ("research", ("课题", "研究", "实验")),
    ):
        if any(term in text for term in terms):
            return scenario
    return "general"


def extract_turn_memories(text: str) -> list[MemoryCandidate]:
    """Extract only explicit user-provided facts/preferences; never infer a profile."""

    safe_text = redact_text(text.strip()).text
    if not safe_text:
        return []
    output: list[MemoryCandidate] = []
    if re.search(r"(我的课题是|我正在研究|我目前负责|我负责|我常用|我使用)", safe_text):
        output.append(MemoryCandidate("L1", _scenario(safe_text), safe_text[:1000]))
    if re.search(
        r"(请记住|记住我|以后(?:请)?|我偏好|我习惯|我喜欢|我不喜欢|我希望以后)",
        safe_text,
    ):
        output.append(MemoryCandidate("L2", _scenario(safe_text), safe_text[:1000]))
    return output


async def save_turn_memories(
    session: AsyncSession,
    *,
    user_id: int,
    college_id: int | None,
    run_id: int,
    source_message_id: int,
    text: str,
    now: datetime | None = None,
) -> list[AiMemory]:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    saved: list[AiMemory] = []
    for candidate in extract_turn_memories(text):
        duplicate = await session.scalar(
            select(AiMemory)
            .where(
                AiMemory.user_id == user_id,
                AiMemory.level == candidate.level,
                AiMemory.scenario == candidate.scenario,
                AiMemory.content == candidate.content,
                AiMemory.status.in_(["ACTIVE", "PENDING_CONFIRMATION"]),
            )
            .with_for_update()
        )
        if duplicate is not None:
            continue
        memory = AiMemory(
            user_id=user_id,
            college_id=college_id,
            level=candidate.level,
            scenario=candidate.scenario,
            content=candidate.content,
            source_message_ids=[source_message_id],
            source_run_ids=[run_id],
            status="ACTIVE" if candidate.level == "L1" else "PENDING_CONFIRMATION",
            expires_at=current + timedelta(days=INITIAL_TTL_DAYS),
        )
        session.add(memory)
        await session.flush()
        saved.append(memory)
    return saved


async def load_relevant_memories(
    session: AsyncSession,
    *,
    user_id: int,
    college_id: int | None,
    query: str,
    now: datetime | None = None,
    limit: int = 8,
    include_archived: bool = False,
    levels: tuple[str, ...] | None = None,
) -> list[AiMemory]:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    statuses = ["ACTIVE", "ARCHIVED"] if include_archived else ["ACTIVE"]
    conditions = [
        AiMemory.user_id == user_id,
        AiMemory.status.in_(statuses),
        (
            AiMemory.expires_at > current
            if not include_archived
            else AiMemory.archived_at.is_not(None)
        ),
    ]
    if levels:
        conditions.append(AiMemory.level.in_(levels))
    if college_id is not None:
        conditions.append(AiMemory.college_id.is_(None) | (AiMemory.college_id == college_id))
    else:
        conditions.append(AiMemory.college_id.is_(None))
    rows = list((await session.scalars(select(AiMemory).where(*conditions))).all())
    scored = [
        (memory, _relevance(query, memory.content))
        for memory in rows
        if _relevance(query, memory.content) > 0
    ]
    scored.sort(
        key=lambda item: (
            0 if item[0].level == "L2" else 1,
            -item[1],
            -item[0].recall_count,
            -item[0].expires_at.timestamp(),
        )
    )
    return [memory for memory, _score in scored[: max(0, limit)]]


async def load_relevant_l0_messages(
    session: AsyncSession,
    *,
    user_id: int,
    query: str,
    exclude_message_ids: set[int] | None = None,
    now: datetime | None = None,
    limit: int = 5,
    include_archived: bool = False,
) -> list[AiMessage]:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    conditions = [AiMessage.user_id == user_id, AiMessage.role.in_(("user", "assistant"))]
    if exclude_message_ids:
        conditions.append(AiMessage.id.not_in(exclude_message_ids))
    if include_archived:
        conditions.append(
            (AiMessage.archived_at.is_not(None))
            | ((AiMessage.archived_at.is_(None)) & (AiMessage.expires_at > current))
        )
    else:
        conditions.extend((AiMessage.archived_at.is_(None), AiMessage.expires_at > current))
    candidates = list(
        (
            await session.scalars(
                select(AiMessage)
                .where(*conditions)
                .order_by(AiMessage.id.desc())
                .limit(1000)
            )
        ).all()
    )
    ranked = [
        (message, _relevance(query, message.content))
        for message in candidates
        if _relevance(query, message.content) >= 0.15
    ]
    ranked.sort(
        key=lambda item: (
            -item[1],
            -item[0].recall_count,
            -(item[0].last_recalled_at or item[0].created_at).timestamp(),
        )
    )
    return [message for message, _score in ranked[: max(0, limit)]]


async def record_valid_recalls(
    session: AsyncSession,
    *,
    run_id: int,
    memories: list[AiMemory],
    used_memory_ids: list[int],
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    used = set(used_memory_ids)
    updated = 0
    for memory in memories:
        if memory.id not in used:
            continue
        locked = await session.scalar(
            select(AiMemory).where(AiMemory.id == memory.id).with_for_update()
        )
        if locked is None or locked.status not in {"ACTIVE", "ARCHIVED"}:
            continue
        prior = await session.scalar(
            select(AiMemoryRecall.id).where(
                AiMemoryRecall.memory_id == locked.id,
                AiMemoryRecall.run_id == run_id,
            )
        )
        if prior is not None:
            continue
        session.add(
            AiMemoryRecall(
                memory_id=locked.id,
                run_id=run_id,
                used_in_response=True,
                recalled_at=current,
            )
        )
        locked.recall_count += 1
        locked.last_recalled_at = current
        locked.expires_at = current + timedelta(days=memory_ttl_days(locked.recall_count))
        if locked.status == "ARCHIVED":
            locked.status = "ACTIVE"
            locked.archived_at = None
        updated += 1
    if updated:
        await session.flush()
    return updated


async def record_valid_l0_recalls(
    session: AsyncSession,
    *,
    run_id: int,
    messages: list[AiMessage],
    used_message_ids: list[int],
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    used = set(used_message_ids)
    updated = 0
    for message in messages:
        if message.id not in used:
            continue
        locked = await session.scalar(
            select(AiMessage).where(AiMessage.id == message.id).with_for_update()
        )
        expired_archive = (
            locked is not None
            and locked.archived_at is not None
            and locked.archived_at <= current - timedelta(days=ARCHIVE_GRACE_DAYS)
        )
        if locked is None or expired_archive:
            continue
        prior = await session.scalar(
            select(AiMessageRecall.id).where(
                AiMessageRecall.message_id == locked.id,
                AiMessageRecall.run_id == run_id,
            )
        )
        if prior is not None:
            continue
        session.add(AiMessageRecall(message_id=locked.id, run_id=run_id, recalled_at=current))
        locked.recall_count += 1
        locked.last_recalled_at = current
        locked.expires_at = current + timedelta(days=memory_ttl_days(locked.recall_count))
        locked.archived_at = None
        updated += 1
    if updated:
        await session.flush()
    return updated


async def confirm_l2_memory(
    session: AsyncSession,
    *,
    user_id: int,
    memory_id: int,
    now: datetime | None = None,
) -> AiMemory | None:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    memory = await session.scalar(
        select(AiMemory)
        .where(
            AiMemory.id == memory_id,
            AiMemory.user_id == user_id,
            AiMemory.level == "L2",
            AiMemory.status == "PENDING_CONFIRMATION",
        )
        .with_for_update()
    )
    if memory is None:
        return None
    memory.status = "ACTIVE"
    memory.expires_at = current + timedelta(days=INITIAL_TTL_DAYS)
    await session.flush()
    return memory


async def reject_l2_memory(
    session: AsyncSession,
    *,
    user_id: int,
    memory_id: int,
    now: datetime | None = None,
) -> AiMemory | None:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    memory = await session.scalar(
        select(AiMemory)
        .where(
            AiMemory.id == memory_id,
            AiMemory.user_id == user_id,
            AiMemory.level == "L2",
            AiMemory.status == "PENDING_CONFIRMATION",
        )
        .with_for_update()
    )
    if memory is None:
        return None
    memory.status = "REJECTED"
    memory.updated_at = current
    await session.flush()
    return memory


async def find_memories_forget_preview(
    session: AsyncSession,
    *,
    user_id: int,
    topic: str,
    limit: int = 50,
) -> list[AiMemory]:
    topic_terms = _terms(topic)
    if not topic_terms:
        return []
    rows = list(
        (
            await session.scalars(
                select(AiMemory)
                .where(
                    AiMemory.user_id == user_id,
                    AiMemory.status.in_(["ACTIVE", "PENDING_CONFIRMATION", "ARCHIVED"]),
                )
                .order_by(AiMemory.updated_at.desc(), AiMemory.id.desc())
                .limit(limit * 4)
            )
        ).all()
    )
    matches = [memory for memory in rows if _relevance(topic, memory.content) >= 0.25]
    matches.sort(key=lambda memory: (_relevance(topic, memory.content), memory.id), reverse=True)
    return matches[:limit]


async def invalidate_memories(
    session: AsyncSession,
    *,
    user_id: int,
    memory_ids: list[int],
    now: datetime | None = None,
) -> int:
    if not memory_ids:
        return 0
    rows = list(
        (
            await session.scalars(
                select(AiMemory)
                .where(
                    AiMemory.id.in_(memory_ids),
                    AiMemory.user_id == user_id,
                    AiMemory.status.in_(["ACTIVE", "PENDING_CONFIRMATION", "ARCHIVED"]),
                )
                .with_for_update()
            )
        ).all()
    )
    current = now or datetime.now(UTC).replace(tzinfo=None)
    for memory in rows:
        memory.status = "INVALID"
        memory.updated_at = current
    return len(rows)
