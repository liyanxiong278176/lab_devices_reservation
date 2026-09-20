from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from sqlalchemy import and_, delete, exists, or_, select, update

from app.infrastructure.cache.cache import CacheService
from app.infrastructure.cache.redis import get_redis_circuit, get_redis_for_app
from app.infrastructure.db.models import Notification, OutboxTask, Reservation, ReservationItem
from app.infrastructure.db.session import build_session_factory

logger = logging.getLogger(__name__)


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


ClaimedTask = tuple[int, str, str, dict[str, Any], str | None]


class OutboxWorker:
    """A restart-safe worker backed by MySQL/SQLite task rows.

    Different aggregate keys can run concurrently. A second task for the same
    aggregate is not claimed while an earlier task is PROCESSING, preserving
    business ordering without serializing the whole queue.
    """

    def __init__(self, app: FastAPI, poll_seconds: float = 1.0) -> None:
        self.app = app
        self.poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="lab-outbox-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def run_once(self) -> bool:
        claimed = await self._claim_one()
        if claimed is None:
            return False
        await self._process_claimed(claimed)
        return True

    async def _process_claimed(self, claimed: ClaimedTask) -> None:
        task_id, task_key, task_type, payload, _aggregate_key = claimed
        try:
            await asyncio.wait_for(
                self._handle(task_type, payload, task_key),
                timeout=float(self.app.state.settings.outbox_task_timeout_seconds),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - exercised by retry tests
            logger.exception("outbox task failed: %s", task_id)
            await self._mark_failed(task_id, str(exc), exc)
        else:
            await self._mark_completed(task_id)

    async def _run(self) -> None:
        active: set[asyncio.Task[None]] = set()
        concurrency = max(1, int(self.app.state.settings.outbox_worker_concurrency))
        try:
            while not self._stop.is_set():
                while len(active) < concurrency and not self._stop.is_set():
                    claimed = await self._claim_one()
                    if claimed is None:
                        break
                    active.add(asyncio.create_task(self._process_claimed(claimed)))

                if active:
                    done, pending = await asyncio.wait(
                        active,
                        timeout=self.poll_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    active = set(pending)
                    for task in done:
                        try:
                            task.result()
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            # The task has already attempted its own retry
                            # transition. Keep the worker alive if that
                            # transition itself failed because the database
                            # was temporarily unavailable.
                            logger.exception("outbox task wrapper failed")
                else:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                    except TimeoutError:
                        continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox worker loop failed")
            await asyncio.sleep(min(self.poll_seconds * 4, 10))
        finally:
            if active:
                await asyncio.gather(*active, return_exceptions=True)

    async def _session_factory(self):
        factory = getattr(self.app.state, "session_factory", None)
        if factory is None:
            from app.infrastructure.db.session import build_engine

            engine = build_engine(self.app.state.settings)
            self.app.state.db_engine = engine
            factory = build_session_factory(engine)
            self.app.state.session_factory = factory
        return factory

    async def _claim_one(self) -> ClaimedTask | None:
        factory = await self._session_factory()
        async with factory() as session:
            async with session.begin():
                now = utcnow_naive()
                stale_before = now - timedelta(
                    seconds=self.app.state.settings.outbox_claim_timeout_seconds
                )
                stmt = (
                    select(OutboxTask)
                    .where(
                        or_(
                            OutboxTask.status == "PENDING",
                            and_(
                                OutboxTask.status == "PROCESSING",
                                OutboxTask.claimed_at <= stale_before,
                            ),
                        ),
                        OutboxTask.execute_at <= now,
                        OutboxTask.attempts < self.app.state.settings.outbox_max_attempts,
                    )
                    .order_by(OutboxTask.execute_at, OutboxTask.id)
                    .limit(max(10, self.app.state.settings.outbox_worker_concurrency * 4))
                    .with_for_update(skip_locked=True)
                )
                candidates = list((await session.scalars(stmt)).all())
                task: OutboxTask | None = None
                for candidate in candidates:
                    if candidate.aggregate_key:
                        blocked = await session.scalar(
                            select(exists().where(
                                OutboxTask.aggregate_key == candidate.aggregate_key,
                                OutboxTask.status == "PROCESSING",
                                OutboxTask.id != candidate.id,
                            ))
                        )
                        if blocked:
                            continue
                    task = candidate
                    break
                if task is None:
                    return None
                task.status = "PROCESSING"
                task.claimed_at = now
                task.attempts += 1
                self._metric("outbox_claimed_total", labels={"task_type": task.task_type})
                return (
                    task.id,
                    task.task_key,
                    task.task_type,
                    dict(task.payload or {}),
                    task.aggregate_key,
                )

    async def _mark_completed(self, task_id: int) -> None:
        factory = await self._session_factory()
        async with factory() as session:
            result = await session.execute(
                update(OutboxTask)
                .where(OutboxTask.id == task_id, OutboxTask.status == "PROCESSING")
                .values(status="COMPLETED", completed_at=utcnow_naive())
            )
            await session.commit()
            if result.rowcount:
                self._metric("outbox_completed_total")

    async def _mark_failed(self, task_id: int, error: str, exc: Exception) -> None:
        factory = await self._session_factory()
        async with factory() as session:
            task = await session.scalar(select(OutboxTask).where(OutboxTask.id == task_id))
            if task is None:
                return
            max_attempts = int(self.app.state.settings.outbox_max_attempts)
            permanent = isinstance(exc, (ValueError, KeyError, TypeError))
            should_fail = permanent or task.attempts >= max_attempts
            task.status = "FAILED" if should_fail else "PENDING"
            task.last_error = error[:2000]
            if not should_fail:
                base = int(self.app.state.settings.outbox_retry_base_seconds)
                delay = min(3600, base * (2 ** max(0, task.attempts - 1)))
                task.execute_at = utcnow_naive() + timedelta(
                    seconds=delay + random.uniform(0, max(1, delay // 4))
                )
            await session.commit()
            self._metric(
                "outbox_failed_total",
                labels={"status": task.status, "task_type": task.task_type},
            )

    async def _handle(
        self,
        task_type: str,
        payload: dict[str, Any],
        task_key: str | None = None,
    ) -> None:
        factory = await self._session_factory()
        if task_type == "NOTIFICATION":
            async with factory() as session:
                if task_key is not None and await session.scalar(
                    select(Notification).where(Notification.source_task_key == task_key)
                ):
                    return
                session.add(
                    Notification(
                        user_id=int(payload["user_id"]),
                        college_id=payload.get("college_id"),
                        type=str(payload.get("type", "SYSTEM")),
                        title=str(payload.get("title", "系统通知"))[:200],
                        content=str(payload.get("content", ""))[:1000],
                        related_id=payload.get("related_id"),
                        related_type=payload.get("related_type"),
                        source_task_key=task_key,
                    )
                )
                await session.commit()
            return

        if task_type == "RESERVATION_NO_SHOW":
            reservation_id = int(payload["reservation_id"])
            async with factory() as session:
                result = await session.execute(
                    update(Reservation)
                    .where(Reservation.id == reservation_id, Reservation.status == "APPROVED")
                    .values(status="NO_SHOW")
                )
                if result.rowcount:
                    await session.execute(
                        delete(ReservationItem).where(
                            ReservationItem.reservation_id == reservation_id
                        )
                    )
                    session.add(
                        OutboxTask(
                            task_key=f"notification:reservation:{reservation_id}:no-show",
                            task_type="NOTIFICATION",
                            aggregate_key=f"reservation:{reservation_id}",
                            college_id=payload.get("college_id"),
                            payload={
                                "user_id": payload["user_id"],
                                "college_id": payload.get("college_id"),
                                "type": "RESERVATION_NO_SHOW",
                                "title": "预约已标记未签到",
                                "content": "预约开始日结束前未完成签到，系统已自动释放设备。",
                                "related_id": reservation_id,
                                "related_type": "RESERVATION",
                            },
                            execute_at=utcnow_naive(),
                        )
                    )
                await session.commit()
            return

        if task_type == "CACHE_BUMP":
            scope = str(payload["scope"])
            cache = CacheService(
                get_redis_for_app(self.app),
                self.app.state.settings,
                getattr(self.app.state, "metrics", None),
                get_redis_circuit(self.app),
            )
            await cache.bump_version(scope)
            return

        raise ValueError(f"unsupported outbox task type: {task_type}")

    def _metric(self, name: str, labels: dict[str, object] | None = None) -> None:
        metrics = getattr(self.app.state, "metrics", None)
        if metrics is not None:
            metrics.increment(name, labels=labels)
