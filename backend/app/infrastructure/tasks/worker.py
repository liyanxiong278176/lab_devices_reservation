from __future__ import annotations

import asyncio
import logging
import random
import secrets
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import selectinload

from app.application.exports import csv_chunk_text, iter_export_rows
from app.application.lifecycle import append_audit, change_device_status
from app.auth.security import Principal
from app.infrastructure.cache.cache import CacheService
from app.infrastructure.cache.redis import get_redis_circuit, get_redis_for_app
from app.infrastructure.db.models import (
    AiEmbeddingRebuildJob,
    College,
    CreditEvent,
    Device,
    DeviceHandover,
    ExportTask,
    KnowledgeDocument,
    Lab,
    Notification,
    OutboxTask,
    RepairReport,
    RepairWorklog,
    Reservation,
    ReservationBlackout,
    ReservationItem,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    Role,
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
                timeout=(
                    max(120.0, self.app.state.settings.ai_provider_timeout_seconds * 4)
                    if task_type == "AI_RUN"
                    else 120.0
                    if task_type == "AI_KNOWLEDGE_PARSE"
                    else max(180.0, self.app.state.settings.ai_provider_timeout_seconds * 4)
                    if task_type == "AI_EMBEDDING_REBUILD"
                    else float(self.app.state.settings.outbox_task_timeout_seconds)
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - exercised by retry tests
            if task_type.startswith("AI_"):
                logger.error(
                    "outbox AI task failed; task_id=%s error_type=%s",
                    task_id,
                    type(exc).__name__,
                )
                error = f"AI background task failed ({type(exc).__name__})"
            else:
                logger.exception("outbox task failed: %s", task_id)
                error = str(exc)
            await self._mark_failed(task_id, error, exc)
        else:
            await self._mark_completed(task_id)

    async def _run(self) -> None:
        active: set[asyncio.Task[None]] = set()
        concurrency = max(1, int(self.app.state.settings.outbox_worker_concurrency))
        poll_failures = 0
        try:
            while not self._stop.is_set():
                if poll_failures:
                    delay = min(max(self.poll_seconds, 0.1) * (2 ** (poll_failures - 1)), 30.0)
                    await self._wait_for_stop(delay)
                    if self._stop.is_set():
                        break
                poll_failed = False
                while len(active) < concurrency and not self._stop.is_set():
                    try:
                        claimed = await self._claim_one()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # A transient database outage must not permanently
                        # stop the in-process worker. Retry the queue after
                        # the dependency recovers.
                        logger.exception("outbox task polling failed")
                        poll_failed = True
                        poll_failures = min(poll_failures + 1, 10)
                        break
                    if claimed is None:
                        break
                    active.add(asyncio.create_task(self._process_claimed(claimed)))

                if not poll_failed:
                    poll_failures = 0

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
                elif not poll_failed:
                    await self._wait_for_stop(self.poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox worker loop failed")
            await asyncio.sleep(min(self.poll_seconds * 4, 10))
        finally:
            if active:
                await asyncio.gather(*active, return_exceptions=True)

    async def _wait_for_stop(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=timeout)
        except TimeoutError:
            pass

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
                max_attempts = int(self.app.state.settings.outbox_max_attempts)
                exhausted = list(
                    (
                        await session.scalars(
                            select(OutboxTask)
                            .where(
                                OutboxTask.status == "PROCESSING",
                                or_(
                                    OutboxTask.claimed_at <= stale_before,
                                    OutboxTask.claimed_at.is_(None),
                                ),
                                OutboxTask.attempts >= max_attempts,
                            )
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                for expired in exhausted:
                    expired.status = "FAILED"
                    expired.claimed_at = None
                    expired.last_error = (
                        f"Worker lease expired after reaching the maximum of "
                        f"{max_attempts} attempts"
                    )
                if exhausted:
                    await session.flush()
                    for expired in exhausted:
                        self._metric(
                            "outbox_failed_total",
                            labels={"status": "FAILED", "task_type": expired.task_type},
                        )
                stmt = (
                    select(OutboxTask)
                    .where(
                        or_(
                            OutboxTask.status == "PENDING",
                            and_(
                                OutboxTask.status == "PROCESSING",
                                or_(
                                    OutboxTask.claimed_at <= stale_before,
                                    OutboxTask.claimed_at.is_(None),
                                ),
                            ),
                        ),
                        OutboxTask.execute_at <= now,
                        OutboxTask.attempts < max_attempts,
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
            if should_fail and task.task_type in {"AI_KNOWLEDGE_PARSE", "AI_KNOWLEDGE_POLL"}:
                document_id = (task.payload or {}).get("document_id")
                if document_id is not None:
                    document = await session.scalar(
                        select(KnowledgeDocument).where(KnowledgeDocument.id == int(document_id))
                    )
                    if document is not None and document.parse_status not in {
                        "PARSED",
                        "REVIEWED",
                        "PUBLISHED",
                    }:
                        document.parse_status = "FAILED"
                        document.parse_error = "文档解析暂时失败，请稍后重试。"
            if should_fail and task.task_type == "AI_EMBEDDING_REBUILD":
                job_id = (task.payload or {}).get("job_id")
                if job_id is not None:
                    job = await session.scalar(
                        select(AiEmbeddingRebuildJob).where(AiEmbeddingRebuildJob.id == int(job_id))
                    )
                    if job is not None and job.status not in {"COMPLETED", "ROLLED_BACK"}:
                        job.status = "FAILED"
                        job.error_code = "AI_EMBEDDING_REBUILD_FAILED"
                        job.completed_at = utcnow_naive()
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
        if task_type == "AI_RUN":
            from app.ai.runtime import execute_ai_run

            await execute_ai_run(self.app, int(payload["run_id"]))
            return

        if task_type == "AI_KNOWLEDGE_PARSE":
            from app.ai.knowledge import start_mineru_parse

            await start_mineru_parse(self.app, int(payload["document_id"]))
            return

        if task_type == "AI_KNOWLEDGE_POLL":
            from app.ai.knowledge import poll_mineru_parse

            await poll_mineru_parse(
                self.app,
                int(payload["document_id"]),
                str(payload["batch_id"]),
                int(payload.get("attempt", 0)),
            )
            return

        if task_type == "AI_EMBEDDING_REBUILD":
            from app.ai.embedding_rebuild import process_embedding_rebuild_batch

            await process_embedding_rebuild_batch(self.app, int(payload["job_id"]))
            return

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

        if task_type == "REPAIR_SLA_REMINDER":
            report_id = int(payload["report_id"])
            kind = str(payload["kind"])
            if kind not in {"response", "resolve"}:
                raise ValueError(f"unsupported repair SLA reminder kind: {kind}")

            now = utcnow_naive()
            async with factory() as session:
                async with session.begin():
                    report = await session.scalar(
                        select(RepairReport).where(RepairReport.id == report_id).with_for_update()
                    )
                    if report is None:
                        return

                    if kind == "response":
                        eligible = (
                            report.status == "PENDING"
                            and report.response_due_at is not None
                            and report.response_due_at <= now
                        )
                        title = "报修响应已超时"
                        content_template = (
                            "设备“{device_name}”的报修工单“{report_title}”尚未受理，"
                            "已超过响应时限。"
                        )
                    else:
                        eligible = (
                            report.status == "PROCESSING"
                            and report.resolve_due_at is not None
                            and report.resolve_due_at <= now
                        )
                        title = "报修处理已超时"
                        content_template = (
                            "设备“{device_name}”的报修工单“{report_title}”尚未完成处理，"
                            "已超过处理时限。"
                        )
                    if not eligible:
                        return

                    device_info = (
                        await session.execute(
                            select(Device.name, Lab.manager_id, College.manager_id)
                            .join(College, College.id == Device.college_id)
                            .outerjoin(Lab, Lab.id == Device.lab_id)
                            .where(Device.id == report.device_id)
                        )
                    ).one_or_none()
                    if device_info is None:
                        return

                    device_name, lab_manager_id, college_manager_id = device_info
                    recipient_ids = {
                        int(user_id)
                        for user_id in (report.handler_id, lab_manager_id, college_manager_id)
                        if user_id is not None
                    }
                    active_recipient_ids = (
                        set(
                            (
                                await session.scalars(
                                    select(User.id).where(
                                        User.id.in_(recipient_ids),
                                        User.status == 1,
                                    )
                                )
                            ).all()
                        )
                        if recipient_ids
                        else set()
                    )
                    if not active_recipient_ids:
                        active_recipient_ids = set(
                            (
                                await session.scalars(
                                    select(User.id)
                                    .join(User.roles)
                                    .where(Role.role_code == "SYS_ADMIN", User.status == 1)
                                )
                            ).all()
                        )

                    content = content_template.format(
                        device_name=device_name,
                        report_title=report.title,
                    )
                    for user_id in sorted(active_recipient_ids):
                        notification_key = (
                            f"notification:repair:{report.id}:sla:{kind}:user:{user_id}"
                        )
                        exists_already = await session.scalar(
                            select(OutboxTask.id).where(OutboxTask.task_key == notification_key)
                        )
                        if exists_already is not None:
                            continue
                        session.add(
                            OutboxTask(
                                task_key=notification_key,
                                task_type="NOTIFICATION",
                                aggregate_key=f"repair:{report.id}",
                                college_id=report.college_id,
                                payload={
                                    "user_id": user_id,
                                    "college_id": report.college_id,
                                    "type": "REPAIR_UPDATE",
                                    "title": title,
                                    "content": content,
                                    "related_id": report.id,
                                    "related_type": "REPAIR",
                                },
                                execute_at=now,
                            )
                        )
            return

        if task_type == "RESERVATION_NO_SHOW":
            reservation_id = int(payload["reservation_id"])
            async with factory() as session:
                reservation = await session.scalar(
                    select(Reservation).where(Reservation.id == reservation_id).with_for_update()
                )
                if (
                    reservation is not None
                    and reservation.status == "APPROVED"
                    and reservation.handover_status in {"PENDING", "EXCEPTION"}
                ):
                    exception_at_handover = reservation.handover_status == "EXCEPTION"
                    expected_handover_status = reservation.handover_status
                    next_reservation_status = "CANCELLED" if exception_at_handover else "NO_SHOW"
                    result = await session.execute(
                        update(Reservation)
                        .where(
                            Reservation.id == reservation_id,
                            Reservation.status == "APPROVED",
                            Reservation.handover_status == expected_handover_status,
                        )
                        .values(
                            status=next_reservation_status,
                            handover_status="CANCELLED",
                            reject_reason=(
                                "设备交接发现异常，预约日结束时自动取消；未扣除用户信用分。"
                                if exception_at_handover
                                else None
                            ),
                        )
                    )
                else:
                    result = None

                if result is not None and result.rowcount == 1:
                    await session.execute(
                        update(DeviceHandover)
                        .where(
                            DeviceHandover.reservation_id == reservation_id,
                            DeviceHandover.status == expected_handover_status,
                        )
                        .values(status="CANCELLED", updated_at=utcnow_naive())
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
                    if not exception_at_handover:
                        user = await session.scalar(
                            select(User).where(User.id == reservation.user_id)
                        )
                    else:
                        user = None
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
                                reason="预约首日未完成负责人设备交接",
                                created_at=utcnow_naive(),
                            )
                        )
                    append_audit(
                        session,
                        user_id=reservation.user_id,
                        college_id=reservation.college_id,
                        action=(
                            "RESERVATION_AUTO_CANCEL_HANDOVER_EXCEPTION"
                            if exception_at_handover
                            else "RESERVATION_NO_SHOW"
                        ),
                        target_type="RESERVATION",
                        target_id=reservation_id,
                        detail={"credit_penalty": 0 if exception_at_handover else -10},
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
                            task_key=(
                                f"notification:reservation:{reservation_id}:"
                                "handover-exception-auto-cancel"
                                if exception_at_handover
                                else f"notification:reservation:{reservation_id}:no-show"
                            ),
                            task_type="NOTIFICATION",
                            aggregate_key=f"reservation:{reservation_id}",
                            college_id=payload.get("college_id"),
                            payload={
                                "user_id": reservation.user_id,
                                "college_id": reservation.college_id,
                                "type": (
                                    "RESERVATION_UPDATE"
                                    if exception_at_handover
                                    else "RESERVATION_NO_SHOW"
                                ),
                                "title": (
                                    "设备交接异常，预约已取消"
                                    if exception_at_handover
                                    else "预约已标记爽约"
                                ),
                                "content": (
                                    "设备交接时发现异常，系统已取消预约并释放日期，未扣除信用分。"
                                    if exception_at_handover
                                    else (
                                        "预约首日结束前未完成负责人设备交接，"
                                        "系统已标记爽约并释放设备。"
                                    )
                                ),
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
                device = await session.scalar(
                    select(Device).where(Device.id == device_id).with_for_update()
                )
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
                active_offer = await session.scalar(
                    select(ReservationWaitlistOffer).where(
                        ReservationWaitlistOffer.device_id == device_id,
                        ReservationWaitlistOffer.reservation_date == reservation_date,
                        ReservationWaitlistOffer.expires_at > now,
                    )
                )
                if active_offer is not None:
                    return
                for _ in range(100):
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
                        break
                    if reservation_date < date.today():
                        candidate.status = "SKIPPED"
                        session.add(
                            OutboxTask(
                                task_key=f"notification:waitlist:{candidate.id}:date-passed",
                                task_type="NOTIFICATION",
                                aggregate_key=f"waitlist:{device_id}:{reservation_date.isoformat()}",
                                college_id=candidate.college_id,
                                payload={
                                    "user_id": candidate.user_id,
                                    "college_id": candidate.college_id,
                                    "type": "WAITLIST_EXPIRED",
                                    "title": "候补日期已过期",
                                    "content": "预约日期已过，候补资格已结束。",
                                    "related_id": candidate.id,
                                    "related_type": "WAITLIST",
                                },
                                execute_at=now,
                            )
                        )
                        continue
                    expires_at = now + timedelta(hours=24)
                    offer = ReservationWaitlistOffer(
                        waitlist_id=candidate.id,
                        device_id=device_id,
                        college_id=candidate.college_id,
                        user_id=candidate.user_id,
                        reservation_date=reservation_date,
                        expires_at=expires_at,
                        created_at=now,
                    )
                    session.add(offer)
                    candidate.status = "OFFERED"
                    candidate.notified_at = now
                    session.add(
                        OutboxTask(
                            task_key=f"waitlist:offer-expire:{candidate.id}:{expires_at.strftime('%Y%m%dT%H%M%S')}",
                            task_type="WAITLIST_OFFER_EXPIRE",
                            aggregate_key=f"waitlist:{device_id}:{reservation_date.isoformat()}",
                            college_id=candidate.college_id,
                            payload={"waitlist_id": candidate.id},
                            execute_at=expires_at,
                        )
                    )
                    session.add(
                        OutboxTask(
                            task_key=f"notification:waitlist:{candidate.id}:offer",
                            task_type="NOTIFICATION",
                            aggregate_key=f"waitlist:{device_id}:{reservation_date.isoformat()}",
                            college_id=candidate.college_id,
                            payload={
                                "user_id": candidate.user_id,
                                "college_id": candidate.college_id,
                                "type": "WAITLIST_READY",
                                "title": "候补日期已为你保留",
                                "content": (
                                    f"设备在 {reservation_date.isoformat()} 已为你保留 24 小时。"
                                    "请在“我的预约”中确认，系统会按设备原审批规则创建预约。"
                                ),
                                "related_id": candidate.id,
                                "related_type": "WAITLIST",
                            },
                            execute_at=now,
                        )
                    )
                    break
                await session.commit()
            return

        if task_type == "WAITLIST_OFFER_EXPIRE":
            waitlist_id = int(payload["waitlist_id"])
            async with factory() as session:
                now = utcnow_naive()
                entry = await session.scalar(
                    select(ReservationWaitlist)
                    .where(ReservationWaitlist.id == waitlist_id)
                    .with_for_update()
                )
                offer = await session.scalar(
                    select(ReservationWaitlistOffer)
                    .where(ReservationWaitlistOffer.waitlist_id == waitlist_id)
                    .with_for_update()
                )
                if entry is None or offer is None or entry.status != "OFFERED":
                    return
                if offer.expires_at > now:
                    return
                entry.status = "EXPIRED" if entry.reservation_date >= date.today() else "SKIPPED"
                await session.delete(offer)
                session.add(
                    OutboxTask(
                        task_key=(
                            f"waitlist:promote:{entry.device_id}:"
                            f"{entry.reservation_date.isoformat()}:expired-{entry.id}"
                        ),
                        task_type="WAITLIST_PROMOTE",
                        aggregate_key=f"waitlist:{entry.device_id}:{entry.reservation_date.isoformat()}",
                        college_id=entry.college_id,
                        payload={
                            "device_id": entry.device_id,
                            "reservation_date": entry.reservation_date.isoformat(),
                        },
                        execute_at=now,
                    )
                )
                session.add(
                    OutboxTask(
                        task_key=f"notification:waitlist:{entry.id}:offer-expired",
                        task_type="NOTIFICATION",
                        aggregate_key=f"waitlist:{entry.device_id}:{entry.reservation_date.isoformat()}",
                        college_id=entry.college_id,
                        payload={
                            "user_id": entry.user_id,
                            "college_id": entry.college_id,
                            "type": "WAITLIST_EXPIRED",
                            "title": "候补保留已过期",
                            "content": "24 小时内未确认，候补机会已顺延给下一位。",
                            "related_id": entry.id,
                            "related_type": "WAITLIST",
                        },
                        execute_at=now,
                    )
                )
                await session.commit()
            return

        if task_type == "REPAIR_AUTO_CLOSE":
            report_id = int(payload["report_id"])
            if task_key is None:
                return
            async with factory() as session:
                now = utcnow_naive()
                task = await session.scalar(
                    select(OutboxTask)
                    .where(
                        OutboxTask.task_key == task_key,
                        OutboxTask.task_type == "REPAIR_AUTO_CLOSE",
                    )
                    .with_for_update()
                )
                # A handler may have been claimed just before the user reopened
                # the ticket. Re-read the durable task state before touching the
                # report; cancelled/rescheduled claims are stale and must no-op.
                if task is None or task.status != "PROCESSING" or task.execute_at > now:
                    return
                report = await session.scalar(
                    select(RepairReport).where(
                        RepairReport.id == report_id,
                        RepairReport.status == "RESOLVED",
                    )
                )
                if report is None:
                    return
                # The report may have been reopened after the worker selected
                # it. Close with a compare-and-set so a stale task can never
                # overwrite the user's rejection of the previous resolution.
                result = await session.execute(
                    update(RepairReport)
                    .where(
                        RepairReport.id == report_id,
                        RepairReport.status == "RESOLVED",
                    )
                    .values(
                        status="COMPLETED",
                        user_confirmed_at=now,
                        closed_at=now,
                        user_confirmation_note="用户在确认期限内未反馈，系统自动关闭",
                    )
                )
                if result.rowcount != 1:
                    return
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
                    root = Path(self.app.state.settings.upload_dir).resolve() / "exports"
                    root.mkdir(parents=True, exist_ok=True)
                    token = secrets.token_urlsafe(48)
                    path = root / f"{token}.csv"
                    row_count = 0
                    fieldnames: list[str] | None = None
                    chunk: list[dict[str, Any]] = []
                    with path.open("w", encoding="utf-8-sig", newline="") as handle:
                        async for exported_row in iter_export_rows(
                            session,
                            principal,
                            task.export_type,  # type: ignore[arg-type]
                            task.filters or {},
                        ):
                            if fieldnames is None:
                                fieldnames = list(exported_row.keys())
                            chunk.append(exported_row)
                            row_count += 1
                            if len(chunk) == 500:
                                text = csv_chunk_text(
                                    chunk,
                                    fieldnames,
                                    include_header=row_count == len(chunk),
                                )
                                await asyncio.to_thread(handle.write, text)
                                chunk.clear()
                        if chunk:
                            assert fieldnames is not None
                            text = csv_chunk_text(
                                chunk,
                                fieldnames,
                                include_header=row_count == len(chunk),
                            )
                            await asyncio.to_thread(handle.write, text)
                        if row_count == 0:
                            handle.write("暂无数据\n")
                    now = utcnow_naive()
                    task.status = "COMPLETED"
                    task.file_token = token
                    task.file_path = str(path)
                    task.row_count = row_count
                    task.completed_at = now
                    task.updated_at = now
                    append_audit(
                        session,
                        user_id=task.requester_id,
                        college_id=task.college_id,
                        action="REPORT_EXPORT_COMPLETE",
                        target_type="EXPORT",
                        target_id=task.id,
                        detail={"row_count": row_count},
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
                                "content": f"{task.export_type} 数据已生成，共 {row_count} 条。",
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
