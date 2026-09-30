from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import RepairData, RepairPage
from app.application.lifecycle import append_audit, change_device_status
from app.application.reservations import OPEN_REPAIR_STATUSES, ReservationService
from app.auth.security import Principal, college_scope
from app.core.errors import ApiError
from app.infrastructure.cache.invalidation import (
    enqueue_catalog_cache_bump,
    sync_catalog_cache_bump,
)
from app.infrastructure.db.models import (
    College,
    Device,
    Lab,
    OutboxTask,
    RepairReport,
    RepairWorklog,
)
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _repair_data(report: RepairReport) -> RepairData:
    device = report.__dict__.get("device")
    reporter = report.__dict__.get("reporter")
    return RepairData(
        id=report.id,
        device_id=report.device_id,
        reservation_id=report.reservation_id,
        device_name=device.name if device else f"设备 #{report.device_id}",
        college_id=report.college_id,
        reporter_id=report.reporter_id,
        reporter_name=reporter.real_name if reporter else None,
        title=report.title,
        description=report.description,
        image_urls=report.image_urls,
        status=report.status,
        handler_id=report.handler_id,
        resolution_note=report.resolution_note,
        created_at=report.created_at,
        resolved_at=report.resolved_at,
        priority=report.priority,
        response_due_at=report.response_due_at,
        resolve_due_at=report.resolve_due_at,
        user_confirmed_at=report.user_confirmed_at,
        user_confirmation_note=report.user_confirmation_note,
        closed_at=report.closed_at,
    )


class RepairService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        app: object | None = None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.app = app

    async def _sync_catalog(self, college_id: int | None) -> None:
        if self.app is not None:
            await sync_catalog_cache_bump(self.app, college_id)

    def _scope(self) -> int | None:
        return college_scope(self.principal)

    async def _load(self, report_id: int) -> RepairReport:
        report = await self.session.scalar(
            select(RepairReport)
            .options(
                selectinload(RepairReport.device).selectinload(Device.lab),
                selectinload(RepairReport.reporter),
                selectinload(RepairReport.handler),
            )
            .where(RepairReport.id == report_id)
        )
        if report is None:
            raise ApiError("REPAIR_NOT_FOUND", "报修工单不存在", 404)
        scope = self._scope()
        if scope is not None and report.college_id != scope:
            raise ApiError("REPAIR_NOT_FOUND", "报修工单不存在", 404)
        return report

    async def _can_manage(self, device: Device) -> bool:
        return await ReservationService(self.session, self.principal)._can_manage_device(device)

    async def create(
        self,
        *,
        device_id: int,
        title: str,
        description: str | None,
        image_urls: list[str] | None,
        priority: str = "NORMAL",
    ) -> RepairData:
        if not self.principal.has_permission("repair:create"):
            raise ApiError("FORBIDDEN", "当前账号没有提交报修的权限", 403)
        reservation_service = ReservationService(self.session, self.principal)
        device = await reservation_service._load_device(device_id)
        device = await self.session.scalar(
            select(Device)
            .where(Device.id == device.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if device is None:
            raise ApiError("DEVICE_NOT_FOUND", "设备不存在", 404)
        if device.status in {"DELETED", "RETIRED"}:
            raise ApiError("DEVICE_NOT_REPAIRABLE", "当前设备不支持报修", 409)
        if image_urls:
            image_urls = await reservation_service._validate_evidence_images(image_urls, device)
        report_now = utcnow_naive()
        if priority not in {"NORMAL", "IMPORTANT", "URGENT"}:
            raise ApiError("REPAIR_PRIORITY_INVALID", "报修优先级无效", 422)
        sla_days = self._sla_days(priority)
        report = RepairReport(
            college_id=device.college_id,
            device_id=device.id,
            reporter_id=self.principal.user_id,
            title=title.strip(),
            description=description.strip() if description else None,
            image_urls=image_urls,
            status="PENDING",
            priority=priority,
            response_due_at=report_now + timedelta(days=1),
            resolve_due_at=report_now + timedelta(days=sla_days),
            # Avoid relying on a server default before serializing the newly
            # created object with SQLAlchemy's async driver.
            created_at=report_now,
            updated_at=report_now,
        )
        report.device = device
        self.session.add(report)
        # A reported device is removed from the reservation pool immediately;
        # the manager can restore it after resolving the ticket.
        catalog_changed = device.status not in {"DISABLED", "OFFLINE"}
        if catalog_changed:
            change_device_status(
                self.session,
                device,
                "MAINTENANCE",
                operator_id=self.principal.user_id,
                reason="用户提交设备报修",
            )
            enqueue_catalog_cache_bump(self.session, device.college_id)
        await self.session.flush()
        worklog = RepairWorklog(
            report_id=report.id,
            operator_id=self.principal.user_id,
            status="PENDING",
            content="报修工单已提交",
            image_urls=image_urls,
            created_at=report_now,
        )
        self.session.add(worklog)
        await self.session.flush()
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=report.college_id,
            action="REPAIR_CREATE",
            target_type="REPAIR",
            target_id=report.id,
            detail={"device_id": report.device_id},
        )
        self._notify(
            report,
            event_id=worklog.id,
            title="设备报修已提交",
            content=f"设备“{device.name}”的报修工单已提交，等待负责人受理。",
        )
        self.session.add(
            OutboxTask(
                task_key=f"repair:{report.id}:sla-response",
                task_type="REPAIR_SLA_REMINDER",
                aggregate_key=f"repair:{report.id}",
                college_id=report.college_id,
                payload={"report_id": report.id, "kind": "response"},
                execute_at=report.response_due_at or report_now,
            )
        )
        await self.session.commit()
        if catalog_changed:
            await self._sync_catalog(report.college_id)
        return _repair_data(report)

    async def mine(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> RepairPage:
        if not self.principal.has_permission("repair:read:own"):
            raise ApiError("FORBIDDEN", "当前账号没有查看个人报修的权限", 403)
        conditions = [RepairReport.reporter_id == self.principal.user_id]
        scope = self._scope()
        if scope is not None:
            conditions.append(RepairReport.college_id == scope)
        return await self._page(conditions, page, page_size)

    async def managed(
        self,
        *,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> RepairPage:
        if not (
            self.principal.has_permission("repair:handle")
            or self.principal.has_permission("repair:read:scope")
        ):
            raise ApiError("FORBIDDEN", "当前角色无报修处理权限", 403)
        conditions = []
        if status:
            if status not in {
                "PENDING",
                "PROCESSING",
                "RESOLVED",
                "COMPLETED",
                "REJECTED",
            }:
                raise ApiError("REPAIR_STATUS_INVALID", "报修状态无效", 422)
            conditions.append(RepairReport.status == status)
        scope = self._scope()
        if scope is not None:
            conditions.extend(
                [
                    RepairReport.college_id == scope,
                    or_(
                        Lab.manager_id == self.principal.user_id,
                        College.manager_id == self.principal.user_id,
                    ),
                ]
            )
        return await self._page(
            conditions,
            page,
            page_size,
            managed=True,
        )

    async def _page(
        self,
        conditions: list[object],
        page: int,
        page_size: int,
        *,
        managed: bool = False,
    ) -> RepairPage:
        page_offset(page, page_size)
        id_query = select(RepairReport.id).join(Device, Device.id == RepairReport.device_id)
        if managed:
            id_query = id_query.outerjoin(Lab, Lab.id == Device.lab_id).join(
                College,
                College.id == Device.college_id,
            )
        count_stmt = (
            select(func.count(RepairReport.id))
            .select_from(RepairReport)
            .join(
                Device,
                Device.id == RepairReport.device_id,
            )
        )
        if managed:
            count_stmt = count_stmt.outerjoin(Lab, Lab.id == Device.lab_id).join(
                College,
                College.id == Device.college_id,
            )
        total = int(await self.session.scalar(count_stmt.where(*conditions)) or 0)
        page_ids = delayed_page_ids(
            id_query.where(*conditions),
            RepairReport.id,
            page=page,
            page_size=page_size,
        )
        stmt = (
            select(RepairReport)
            .join(page_ids, page_ids.c.id == RepairReport.id)
            .options(
                selectinload(RepairReport.device),
                selectinload(RepairReport.reporter),
                selectinload(RepairReport.handler),
            )
            .order_by(RepairReport.id.desc())
        )
        reports = list((await self.session.scalars(stmt)).all())
        pages, truncated = page_metadata(total, page_size)
        return RepairPage(
            items=[_repair_data(item) for item in reports],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            truncated=truncated,
        )

    async def take(self, report_id: int) -> RepairData:
        if not self.principal.has_permission("repair:handle"):
            raise ApiError("FORBIDDEN", "当前账号没有受理报修的权限", 403)
        report = await self._load(report_id)
        if not await self._can_manage(report.device):
            raise ApiError("FORBIDDEN", "只能受理自己负责实验室或学院的报修", 403)
        if report.status != "PENDING":
            raise ApiError("INVALID_REPAIR_STATE", "只有待受理工单可以受理", 409)
        result = await self.session.execute(
            update(RepairReport)
            .where(RepairReport.id == report_id, RepairReport.status == "PENDING")
            .values(
                status="PROCESSING",
                handler_id=self.principal.user_id,
                taken_at=utcnow_naive(),
            )
        )
        if result.rowcount != 1:
            raise ApiError("REPAIR_STATE_CHANGED", "工单已被其他负责人受理", 409)
        report.status = "PROCESSING"
        report.handler_id = self.principal.user_id
        report.taken_at = utcnow_naive()
        worklog = RepairWorklog(
            report_id=report.id,
            operator_id=self.principal.user_id,
            status="PROCESSING",
            content="负责人已受理工单",
            created_at=utcnow_naive(),
        )
        self.session.add(worklog)
        await self.session.flush()
        if report.resolve_due_at is not None:
            self.session.add(
                OutboxTask(
                    task_key=f"repair:{report.id}:sla-resolve",
                    task_type="REPAIR_SLA_REMINDER",
                    aggregate_key=f"repair:{report.id}",
                    college_id=report.college_id,
                    payload={"report_id": report.id, "kind": "resolve"},
                    execute_at=report.resolve_due_at,
                )
            )
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=report.college_id,
            action="REPAIR_TAKE",
            target_type="REPAIR",
            target_id=report.id,
        )
        self._notify(
            report,
            event_id=worklog.id,
            title="报修工单已受理",
            content=f"设备“{report.device.name}”的报修工单已受理，负责人正在处理。",
        )
        await self.session.commit()
        return _repair_data(report)

    async def resolve(self, report_id: int, note: str) -> RepairData:
        return await self._finish(report_id, "RESOLVED", note)

    async def reject(self, report_id: int, note: str) -> RepairData:
        return await self._finish(report_id, "REJECTED", note)

    async def _finish(self, report_id: int, status: str, note: str) -> RepairData:
        if not self.principal.has_permission("repair:handle"):
            raise ApiError("FORBIDDEN", "当前账号没有处理报修的权限", 403)
        report = await self._load(report_id)
        if not await self._can_manage(report.device):
            raise ApiError("FORBIDDEN", "只能处理自己负责实验室或学院的报修", 403)
        allowed_statuses = ("PROCESSING",)
        if status == "REJECTED":
            # The management page intentionally offers rejection before taking
            # a ticket. Also allow the assigned handler to reject after taking it.
            allowed_statuses = ("PENDING", "PROCESSING")
        if report.status not in allowed_statuses:
            message = (
                "只有待受理或处理中工单可以驳回"
                if status == "REJECTED"
                else "请先受理工单后再完成此操作"
            )
            raise ApiError("INVALID_REPAIR_STATE", message, 409)
        if report.handler_id not in (None, self.principal.user_id):
            raise ApiError("REPAIR_HANDLER_MISMATCH", "该工单已由其他负责人受理", 409)
        now = utcnow_naive()
        auto_close_task = None
        if status == "RESOLVED":
            # Keep the same lock order as the worker and user confirmation:
            # auto-close task first, then report. This serializes re-resolution
            # against a task that may already have been claimed.
            auto_close_task = await self.session.scalar(
                select(OutboxTask)
                .where(OutboxTask.task_key == f"repair:{report.id}:auto-close")
                .with_for_update()
            )
        expected_status = report.status
        conditions = [RepairReport.id == report_id, RepairReport.status == expected_status]
        if expected_status == "PROCESSING" and report.handler_id is not None:
            conditions.append(RepairReport.handler_id == self.principal.user_id)
        result = await self.session.execute(
            update(RepairReport)
            .where(*conditions)
            .values(
                status=status,
                handler_id=report.handler_id or self.principal.user_id,
                resolution_note=note.strip(),
                resolved_at=now,
            )
        )
        if result.rowcount != 1:
            raise ApiError("REPAIR_STATE_CHANGED", "工单已被其他操作修改", 409)
        report.status = status
        report.handler_id = report.handler_id or self.principal.user_id
        report.resolution_note = note.strip()
        report.resolved_at = now
        worklog = RepairWorklog(
            report_id=report.id,
            operator_id=self.principal.user_id,
            status=status,
            content=note.strip(),
            created_at=now,
        )
        self.session.add(worklog)
        await self.session.flush()
        other_open = int(
            await self.session.scalar(
                select(func.count(RepairReport.id)).where(
                    RepairReport.device_id == report.device_id,
                    RepairReport.status.in_(OPEN_REPAIR_STATUSES),
                    RepairReport.id != report.id,
                )
            )
            or 0
        )
        if (
            status == "REJECTED"
            and other_open == 0
            and report.device.status not in {"DISABLED", "OFFLINE", "RETIRED"}
        ):
            change_device_status(
                self.session,
                report.device,
                "IDLE",
                operator_id=self.principal.user_id,
                reason="报修工单处理完成",
            )
            enqueue_catalog_cache_bump(self.session, report.college_id)
        resolution_label = "处理完成，等待用户确认" if status == "RESOLVED" else "驳回"
        self._notify(
            report,
            event_id=worklog.id,
            title="报修工单状态已更新",
            content=f"设备“{report.device.name}”的报修工单已{resolution_label}。",
        )
        if status == "RESOLVED":
            confirmation_days = int(
                getattr(getattr(self.app, "state", None), "settings", None)
                and getattr(self.app.state.settings, "repair_user_confirmation_days", 3)
                or 3
            )
            if auto_close_task is None:
                auto_close_task = OutboxTask(task_key=f"repair:{report.id}:auto-close")
                self.session.add(auto_close_task)
            auto_close_task.task_type = "REPAIR_AUTO_CLOSE"
            auto_close_task.aggregate_key = f"repair:{report.id}"
            auto_close_task.college_id = report.college_id
            auto_close_task.payload = {"report_id": report.id, "user_id": report.reporter_id}
            auto_close_task.status = "PENDING"
            auto_close_task.attempts = 0
            auto_close_task.execute_at = now + timedelta(days=confirmation_days)
            auto_close_task.claimed_at = None
            auto_close_task.completed_at = None
            auto_close_task.last_error = None
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=report.college_id,
            action="REPAIR_RESOLVE" if status == "RESOLVED" else "REPAIR_REJECT",
            target_type="REPAIR",
            target_id=report.id,
            detail={"note": note.strip()},
        )
        await self.session.commit()
        if other_open == 0 and report.device.status == "IDLE":
            await self._sync_catalog(report.college_id)
        return _repair_data(report)

    def _sla_days(self, priority: str) -> int:
        settings = getattr(self.app, "state", None)
        values = getattr(getattr(settings, "settings", None), "repair_sla_days", None)
        if isinstance(values, dict):
            return max(1, int(values.get(priority, values.get("NORMAL", 3))))
        return {"URGENT": 1, "IMPORTANT": 2, "NORMAL": 3}.get(priority, 3)

    async def confirm(
        self,
        report_id: int,
        *,
        confirmed: bool,
        note: str | None = None,
    ) -> RepairData:
        if not self.principal.has_permission("repair:confirm"):
            raise ApiError("FORBIDDEN", "当前账号没有确认报修结果的权限", 403)
        report = await self._load(report_id)
        if report.reporter_id != self.principal.user_id:
            raise ApiError("FORBIDDEN", "只能确认自己提交的报修工单", 403)
        if report.status != "RESOLVED":
            raise ApiError("INVALID_REPAIR_STATE", "当前工单不在待确认状态", 409)
        # Match the worker's lock order so a confirmation/reopen cannot race a
        # claimed auto-close task and later be overwritten by that stale task.
        auto_close_task = await self.session.scalar(
            select(OutboxTask)
            .where(OutboxTask.task_key == f"repair:{report.id}:auto-close")
            .with_for_update()
        )
        now = utcnow_naive()
        if confirmed:
            next_status = "COMPLETED"
            report.user_confirmed_at = now
            report.closed_at = now
            report.user_confirmation_note = note.strip() if note else None
        else:
            next_status = "PROCESSING"
            report.user_confirmation_note = note.strip() if note else "报修人认为问题尚未解决"
            report.resolved_at = None
        result = await self.session.execute(
            update(RepairReport)
            .where(RepairReport.id == report_id, RepairReport.status == "RESOLVED")
            .values(
                status=next_status,
                user_confirmed_at=now if confirmed else None,
                closed_at=now if confirmed else None,
                user_confirmation_note=report.user_confirmation_note,
                resolved_at=report.resolved_at,
            )
        )
        if result.rowcount != 1:
            raise ApiError("REPAIR_STATE_CHANGED", "工单状态已被其他操作修改", 409)
        worklog = RepairWorklog(
            report_id=report.id,
            operator_id=self.principal.user_id,
            status=next_status,
            content=(note.strip() if note else "报修人确认维修完成")
            if confirmed
            else (note.strip() if note else "报修人退回工单，问题仍未解决"),
            created_at=now,
        )
        self.session.add(worklog)
        await self.session.flush()
        if auto_close_task is not None and auto_close_task.status in {"PENDING", "PROCESSING"}:
            auto_close_task.status = "CANCELLED"
            auto_close_task.claimed_at = None
        if confirmed:
            other_open = int(
                await self.session.scalar(
                    select(func.count(RepairReport.id)).where(
                        RepairReport.device_id == report.device_id,
                        RepairReport.status.in_(OPEN_REPAIR_STATUSES),
                        RepairReport.id != report.id,
                    )
                )
                or 0
            )
            if other_open == 0 and report.device.status not in {"DISABLED", "OFFLINE", "RETIRED"}:
                change_device_status(
                    self.session,
                    report.device,
                    "IDLE",
                    operator_id=self.principal.user_id,
                    reason="报修人确认维修完成",
                )
                enqueue_catalog_cache_bump(self.session, report.college_id)
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=report.college_id,
            action="REPAIR_CONFIRM" if confirmed else "REPAIR_REOPEN",
            target_type="REPAIR",
            target_id=report.id,
            detail={"note": note},
        )
        self._notify(
            report,
            event_id=worklog.id,
            title="报修确认已提交" if confirmed else "报修已退回处理",
            content=(
                f"设备“{report.device.name}”的报修已完成闭环。"
                if confirmed
                else f"设备“{report.device.name}”的报修被退回，负责人将继续处理。"
            ),
        )
        await self.session.commit()
        # Async SQLAlchemy expires scalar attributes on commit. Reload the
        # aggregate with its eager relationships before serializing; otherwise
        # accessing user_confirmed_at after commit triggers MissingGreenlet and
        # turns a successful confirmation into a false HTTP 500.
        report = await self._load(report_id)
        return _repair_data(report)

    async def worklogs(self, report_id: int) -> list[dict[str, object]]:
        report = await self._load(report_id)
        if report.reporter_id != self.principal.user_id and not await self._can_manage(
            report.device
        ):
            raise ApiError("REPAIR_NOT_FOUND", "报修工单不存在或无权访问", 404)
        rows = list(
            (
                await self.session.scalars(
                    select(RepairWorklog)
                    .where(RepairWorklog.report_id == report.id)
                    .order_by(RepairWorklog.created_at, RepairWorklog.id)
                )
            ).all()
        )
        return [
            {
                "id": row.id,
                "report_id": row.report_id,
                "operator_id": row.operator_id,
                "status": row.status,
                "content": row.content,
                "image_urls": row.image_urls,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def _notify(
        self,
        report: RepairReport,
        *,
        event_id: int,
        title: str,
        content: str,
    ) -> None:
        self.session.add(
            OutboxTask(
                task_key=f"notification:repair:{report.id}:worklog:{event_id}",
                task_type="NOTIFICATION",
                aggregate_key=f"repair:{report.id}",
                college_id=report.college_id,
                payload={
                    "user_id": report.reporter_id,
                    "college_id": report.college_id,
                    "type": "REPAIR_UPDATE",
                    "title": title,
                    "content": content,
                    "related_id": report.id,
                    "related_type": "REPAIR",
                },
                execute_at=utcnow_naive(),
            )
        )
