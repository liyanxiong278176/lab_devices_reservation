from __future__ import annotations

import asyncio
import csv
import logging
import random
import secrets
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import selectinload

from app.application.exports import export_rows
from app.application.lifecycle import append_audit, change_device_status
from app.auth.security import Principal
from app.infrastructure.cache.cache import CacheService
from app.infrastructure.cache.redis import get_redis_circuit, get_redis_for_app
from app.infrastructure.db.models import (
    CreditEvent,
    Device,
    ExportTask,
    Notification,
    OutboxTask,
    RepairReport,
    RepairWorklog,
    Reservation,
    ReservationBlackout,
    ReservationItem,
    ReservationWaitlist,
    User,
)
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
                            select(
                                exists().where(
                                    OutboxTask.aggregate_key == candidate.aggregate_key,
                                    OutboxTask.status == "PROCESSING",
                                    OutboxTask.id != candidate.id,
                                )
                            )
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
                now = utcnow_naive()
                notification = Notification(
                    user_id=int(payload["user_id"]),
                    college_id=payload.get("college_id"),
                    type=str(payload.get("type", "SYSTEM")),
                    title=str(payload.get("title", "系统通知"))[:200],
                    content=str(payload.get("content", ""))[:1000],
                    related_id=payload.get("related_id"),
                    related_type=payload.get("related_type"),
                    source_task_key=task_key,
                    created_at=now,
                    updated_at=now,
                )
                session.add(notification)
                await session.flush()
                await session.commit()
                hub = getattr(self.app.state, "notification_hub", None)
                if hub is not None:
                    await hub.publish(
                        notification.user_id,
                        {
                            "id": notification.id,
                            "userId": notification.user_id,
                            "type": notification.type,
                            "title": notification.title,
                            "content": notification.content,
                            "relatedId": notification.related_id,
                            "relatedType": notification.related_type,
                            "isRead": 0,
                            "createdAt": notification.created_at,
                        },
                    )
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
                    reservation = await session.scalar(
                        select(Reservation).where(Reservation.id == reservation_id)
                    )
                    occupied_dates = list(
                        (
                            await session.scalars(
                                select(ReservationItem.reservation_date).where(
                                    ReservationItem.reservation_id == reservation_id
                                )
                            )
                        ).all()
                    )
                    await session.execute(
                        delete(ReservationItem).where(
                            ReservationItem.reservation_id == reservation_id
                        )
                    )
                    user = await session.scalar(
                        select(User).where(User.id == int(payload["user_id"]))
                    )
                    if user is not None:
                        user.credit_score = max(0, user.credit_score - 10)
                        if user.credit_score < self.app.state.settings.credit_block_threshold:
                            user.booking_blocked_until = utcnow_naive() + timedelta(
                                days=self.app.state.settings.credit_block_days
                            )
                        session.add(
                            CreditEvent(
                                user_id=user.id,
                                college_id=user.college_id,
                                reservation_id=reservation_id,
                                event_type="NO_SHOW",
                                points=-10,
                                reason="批准预约未在预约首日完成签到",
                                created_at=utcnow_naive(),
                            )
                        )
                    append_audit(
                        session,
                        user_id=int(payload["user_id"]),
                        college_id=payload.get("college_id"),
                        action="RESERVATION_NO_SHOW",
                        target_type="RESERVATION",
                        target_id=reservation_id,
                        detail={"credit_penalty": -10},
                    )
                    for occupied_date in occupied_dates:
                        session.add(
                            OutboxTask(
                                task_key=(
                                    "waitlist:promote:"
                                    f"{payload.get('device_id', reservation.device_id)}:"
                                    f"{occupied_date.isoformat()}:{reservation_id}"
                                ),
                                task_type="WAITLIST_PROMOTE",
                                aggregate_key=(
                                    f"waitlist:{payload.get('device_id', reservation.device_id)}:"
                                    f"{occupied_date.isoformat()}"
                                ),
                                college_id=payload.get("college_id"),
                                payload={
                                    "device_id": payload.get("device_id", reservation.device_id),
                                    "reservation_date": occupied_date.isoformat(),
                                },
                                execute_at=utcnow_naive(),
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

        if task_type == "WAITLIST_PROMOTE":
            device_id = int(payload["device_id"])
            reservation_date = date.fromisoformat(str(payload["reservation_date"]))
            async with factory() as session:
                candidate = await session.scalar(
                    select(ReservationWaitlist)
                    .where(
                        ReservationWaitlist.device_id == device_id,
                        ReservationWaitlist.reservation_date == reservation_date,
                        ReservationWaitlist.status == "WAITING",
                    )
                    .order_by(ReservationWaitlist.id)
                    .with_for_update(skip_locked=True)
                )
                if candidate is None:
                    return
                device = await session.scalar(select(Device).where(Device.id == device_id))
                if device is None or device.status in {
                    "MAINTENANCE",
                    "DISABLED",
                    "OFFLINE",
                    "RETIRED",
                }:
                    return
                occupied = await session.scalar(
                    select(ReservationItem.id)
                    .join(Reservation, Reservation.id == ReservationItem.reservation_id)
                    .where(
                        ReservationItem.device_id == device_id,
                        ReservationItem.reservation_date == reservation_date,
                        Reservation.status.in_(("PENDING", "APPROVED", "IN_USE")),
                    )
                )
                blocked = await session.scalar(
                    select(ReservationBlackout.id).where(
                        ReservationBlackout.active.is_(True),
                        ReservationBlackout.blocked_date == reservation_date,
                        or_(
                            and_(
                                ReservationBlackout.scope_type == "DEVICE",
                                ReservationBlackout.scope_id == device.id,
                            ),
                            and_(
                                ReservationBlackout.scope_type == "LAB",
                                ReservationBlackout.scope_id == device.lab_id,
                            ),
                            and_(
                                ReservationBlackout.scope_type == "COLLEGE",
                                ReservationBlackout.scope_id == device.college_id,
                            ),
                        ),
                    )
                )
                if occupied is not None or blocked is not None:
                    return
                now = utcnow_naive()
                candidate.status = "NOTIFIED"
                candidate.notified_at = now
                session.add(
                    OutboxTask(
                        task_key=f"notification:waitlist:{candidate.id}:ready",
                        task_type="NOTIFICATION",
                        aggregate_key=f"waitlist:{device_id}:{reservation_date.isoformat()}",
                        college_id=candidate.college_id,
                        payload={
                            "user_id": candidate.user_id,
                            "college_id": candidate.college_id,
                            "type": "WAITLIST_READY",
                            "title": "设备日期已释放",
                            "content": (
                                f"设备在 {reservation_date.isoformat()} 已有空位，"
                                "请尽快重新提交预约。"
                            ),
                            "related_id": candidate.id,
                            "related_type": "WAITLIST",
                        },
                        execute_at=now,
                    )
                )
                await session.commit()
            return

        if task_type == "REPAIR_AUTO_CLOSE":
            report_id = int(payload["report_id"])
            async with factory() as session:
                report = await session.scalar(
                    select(RepairReport).where(
                        RepairReport.id == report_id,
                        RepairReport.status == "RESOLVED",
                    )
                )
                if report is None:
                    return
                now = utcnow_naive()
                report.status = "COMPLETED"
                report.user_confirmed_at = now
                report.closed_at = now
                report.user_confirmation_note = "用户在确认期限内未反馈，系统自动关闭"
                session.add(
                    RepairWorklog(
                        report_id=report.id,
                        operator_id=report.handler_id or report.reporter_id,
                        status="COMPLETED",
                        content="用户超时未反馈，系统自动关闭工单",
                        created_at=now,
                    )
                )
                other_open = int(
                    await session.scalar(
                        select(func.count(RepairReport.id)).where(
                            RepairReport.device_id == report.device_id,
                            RepairReport.status.in_(("PENDING", "PROCESSING", "RESOLVED")),
                            RepairReport.id != report.id,
                        )
                    )
                    or 0
                )
                device = await session.scalar(select(Device).where(Device.id == report.device_id))
                if (
                    device is not None
                    and other_open == 0
                    and device.status not in {"DISABLED", "OFFLINE", "RETIRED"}
                ):
                    change_device_status(
                        session,
                        device,
                        "IDLE",
                        operator_id=report.handler_id or report.reporter_id,
                        reason="用户确认超时，系统自动关闭报修",
                    )
                append_audit(
                    session,
                    user_id=report.handler_id or report.reporter_id,
                    college_id=report.college_id,
                    action="REPAIR_AUTO_CLOSE",
                    target_type="REPAIR",
                    target_id=report.id,
                )
                session.add(
                    OutboxTask(
                        task_key=f"notification:repair:{report.id}:auto-closed",
                        task_type="NOTIFICATION",
                        aggregate_key=f"repair:{report.id}",
                        college_id=report.college_id,
                        payload={
                            "user_id": report.reporter_id,
                            "college_id": report.college_id,
                            "type": "REPAIR_UPDATE",
                            "title": "报修工单已自动关闭",
                            "content": "在确认期限内未收到反馈，系统已自动完成工单。",
                            "related_id": report.id,
                            "related_type": "REPAIR",
                        },
                        execute_at=now,
                    )
                )
                await session.commit()
            return

        if task_type == "EXPORT_GENERATE":
            export_id = int(payload["export_id"])
            async with factory() as session:
                task = await session.scalar(select(ExportTask).where(ExportTask.id == export_id))
                if task is None or task.status not in {"PENDING", "PROCESSING"}:
                    return
                task.status = "PROCESSING"
                task.updated_at = utcnow_naive()
                await session.commit()
                task = await session.scalar(select(ExportTask).where(ExportTask.id == export_id))
                if task is None:
                    return
                user = await session.scalar(
                    select(User)
                    .options(selectinload(User.roles))
                    .where(User.id == task.requester_id)
                )
                if user is None:
                    task.status = "FAILED"
                    task.error = "导出发起人不存在"
                    await session.commit()
                    return
                principal = Principal(
                    user_id=user.id,
                    username=user.username,
                    college_id=user.college_id,
                    roles=tuple(role.role_code for role in user.roles),
                    token_type="access",
                    token_id=f"export-{task.id}",
                )
                try:
                    rows = await export_rows(
                        session,
                        principal,
                        task.export_type,  # type: ignore[arg-type]
                        task.filters or {},
                    )
                    root = Path(self.app.state.settings.upload_dir).resolve() / "exports"
                    root.mkdir(parents=True, exist_ok=True)
                    token = secrets.token_urlsafe(48)
                    path = root / f"{token}.csv"
                    with path.open("w", encoding="utf-8-sig", newline="") as handle:
                        if rows:
                            writer = csv.DictWriter(
                                handle,
                                fieldnames=list(rows[0].keys()),
                                extrasaction="ignore",
                            )
                            writer.writeheader()
                            writer.writerows(rows)
                        else:
                            handle.write("暂无数据\n")
                    now = utcnow_naive()
                    task.status = "COMPLETED"
                    task.file_token = token
                    task.file_path = str(path)
                    task.row_count = len(rows)
                    task.completed_at = now
                    task.updated_at = now
                    append_audit(
                        session,
                        user_id=task.requester_id,
                        college_id=task.college_id,
                        action="REPORT_EXPORT_COMPLETE",
                        target_type="EXPORT",
                        target_id=task.id,
                        detail={"row_count": len(rows)},
                    )
                    session.add(
                        OutboxTask(
                            task_key=f"notification:export:{task.id}:complete",
                            task_type="NOTIFICATION",
                            aggregate_key=f"export:{task.id}",
                            college_id=task.college_id,
                            payload={
                                "user_id": task.requester_id,
                                "college_id": task.college_id,
                                "type": "REPORT_EXPORT",
                                "title": "导出任务已完成",
                                "content": f"{task.export_type} 数据已生成，共 {len(rows)} 条。",
                                "related_id": task.id,
                                "related_type": "EXPORT",
                            },
                            execute_at=now,
                        )
                    )
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    task = await session.scalar(
                        select(ExportTask).where(ExportTask.id == export_id)
                    )
                    if task is not None:
                        task.status = "FAILED"
                        task.error = str(exc)[:1000]
                        task.updated_at = utcnow_naive()
                        await session.commit()
                    raise
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
