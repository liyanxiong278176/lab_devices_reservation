from __future__ import annotations

import calendar
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import (
    MaintenancePlanData,
    MaintenancePlanPage,
    MaintenancePlanWrite,
    MaintenanceRecordCreate,
    MaintenanceRecordData,
    MaintenanceRecordPage,
)
from app.application.lifecycle import append_audit, change_device_status
from app.application.reservations import ReservationService
from app.application.scope_access import manageable_device_ids_statement
from app.auth.security import Principal, college_scope
from app.core.errors import ApiError
from app.infrastructure.cache.invalidation import (
    enqueue_catalog_cache_bump,
    sync_catalog_cache_bump,
)
from app.infrastructure.db.models import (
    Device,
    DeviceMaintenancePlan,
    DeviceMaintenanceRecord,
    OutboxTask,
    RepairReport,
    RepairWorklog,
    Reservation,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    UploadAsset,
)
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset

REQUIRED_EVIDENCE_TYPES = {"CALIBRATION", "SAFETY_CHECK"}


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def add_interval(value: date, amount: int, unit: str) -> date:
    if unit == "DAY":
        return value + timedelta(days=amount)
    months = amount if unit == "MONTH" else amount * 12
    absolute_month = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(absolute_month, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _request_hash(payload: MaintenanceRecordCreate, evidence_asset_id: int | None) -> str:
    normalized = payload.model_dump(mode="json")
    normalized["evidence_asset_id"] = evidence_asset_id
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


class MaintenanceService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        app: object | None = None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.app = app

    def _api_prefix(self) -> str:
        settings = getattr(getattr(self.app, "state", None), "settings", None)
        return str(getattr(settings, "api_prefix", "/api/v2"))

    async def _managed_device(self, device_id: int, *, lock: bool = False) -> Device:
        reservations = ReservationService(self.session, self.principal)
        device = await reservations._load_device(device_id)
        if not await reservations._can_manage_device(device):
            raise ApiError("FORBIDDEN", "只能管理自己负责范围内的设备维护计划", 403)
        if not lock:
            return device
        locked = await self.session.scalar(
            select(Device)
            .options(selectinload(Device.lab), selectinload(Device.college))
            .where(Device.id == device.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked is None:
            raise ApiError("DEVICE_NOT_FOUND", "设备不存在", 404)
        # The device may have been reassigned while the authorization check
        # above was running.  Base the final decision on the locked, refreshed
        # ownership data rather than the stale relationship.
        if not await reservations._can_manage_device(locked):
            raise ApiError("FORBIDDEN", "只能管理自己负责范围内的设备维护计划", 403)
        return locked

    async def _managed_plan(self, plan_id: int, *, lock: bool = False) -> DeviceMaintenancePlan:
        statement = (
            select(DeviceMaintenancePlan)
            .options(selectinload(DeviceMaintenancePlan.device))
            .where(DeviceMaintenancePlan.id == plan_id)
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        plan = await self.session.scalar(statement)
        if plan is None:
            raise ApiError("MAINTENANCE_PLAN_NOT_FOUND", "维护计划不存在", 404)
        if not await ReservationService(self.session, self.principal)._can_manage_device(
            plan.device
        ):
            raise ApiError("MAINTENANCE_PLAN_NOT_FOUND", "维护计划不存在或无权操作", 404)
        return plan

    async def _check_downtime_conflicts(
        self,
        device_id: int,
        start: date | None,
        end: date | None,
    ) -> None:
        if start is None or end is None:
            return
        conditions = [
            Reservation.device_id == device_id,
            Reservation.status.in_(("PENDING", "APPROVED", "IN_USE")),
            Reservation.start_date <= end,
            Reservation.end_date >= start,
        ]
        conflicts = list(
            (
                await self.session.execute(
                    select(
                        Reservation.id,
                        Reservation.start_date,
                        Reservation.end_date,
                        Reservation.status,
                    )
                    .where(*conditions)
                    .order_by(Reservation.start_date, Reservation.id)
                )
            ).all()
        )
        waitlist_holds = list(
            (
                await self.session.execute(
                    select(
                        ReservationWaitlist.id,
                        ReservationWaitlistOffer.reservation_date,
                    )
                    .join(
                        ReservationWaitlistOffer,
                        ReservationWaitlistOffer.waitlist_id == ReservationWaitlist.id,
                    )
                    .where(
                        ReservationWaitlistOffer.device_id == device_id,
                        ReservationWaitlistOffer.reservation_date >= start,
                        ReservationWaitlistOffer.reservation_date <= end,
                        ReservationWaitlistOffer.expires_at > utcnow_naive(),
                        ReservationWaitlist.status == "OFFERED",
                    )
                    .order_by(ReservationWaitlistOffer.reservation_date, ReservationWaitlist.id)
                )
            ).all()
        )
        if conflicts or waitlist_holds:
            raise ApiError(
                "MAINTENANCE_DOWNTIME_CONFLICT",
                "计划停机日期与已有预约冲突，请先由负责人处理预约或调整停机日期",
                409,
                data={
                    "conflicts": [
                        {
                            "reservation_id": row.id,
                            "start_date": row.start_date.isoformat(),
                            "end_date": row.end_date.isoformat(),
                            "status": row.status,
                        }
                        for row in conflicts
                    ]
                    + [
                        {
                            "reservation_id": None,
                            "waitlist_id": row.id,
                            "start_date": row.reservation_date.isoformat(),
                            "end_date": row.reservation_date.isoformat(),
                            "status": "WAITLIST_HOLD",
                        }
                        for row in waitlist_holds
                    ],
                },
            )

    def _schedule_due_notification(self, plan: DeviceMaintenancePlan) -> None:
        now = utcnow_naive()
        due_at = datetime.combine(plan.due_date, time.min)
        if due_at < now:
            due_at = now
        self.session.add(
            OutboxTask(
                task_key=(f"maintenance:{plan.id}:due:{plan.due_date.isoformat()}:{uuid4().hex}"),
                task_type="MAINTENANCE_DUE",
                aggregate_key=f"maintenance:{plan.id}",
                college_id=plan.college_id,
                payload={"plan_id": plan.id, "due_date": plan.due_date.isoformat()},
                execute_at=due_at,
            )
        )

    async def _plan_data(
        self,
        plan: DeviceMaintenancePlan,
        warnings: dict[int, str] | None = None,
    ) -> MaintenancePlanData:
        if warnings is None:
            warnings = await ReservationService(self.session, self.principal)._maintenance_warnings(
                [plan.device_id]
            )
        return MaintenancePlanData(
            id=plan.id,
            device_id=plan.device_id,
            device_name=plan.device.name,
            device_asset_code=plan.device.asset_code,
            college_id=plan.college_id,
            plan_type=plan.plan_type,  # type: ignore[arg-type]
            title=plan.title,
            interval_value=plan.interval_value,
            interval_unit=plan.interval_unit,  # type: ignore[arg-type]
            due_date=plan.due_date,
            downtime_start=plan.downtime_start,
            downtime_end=plan.downtime_end,
            active=plan.active,
            temporarily_unbookable=plan.device_id in warnings,
            unbookable_reason=warnings.get(plan.device_id),
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )

    async def list_plans(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        device_id: int | None = None,
        active: bool | None = None,
    ) -> MaintenancePlanPage:
        if not self.principal.has_permission("maintenance:manage"):
            raise ApiError("FORBIDDEN", "只有负责人可以查看维护计划", 403)
        page_offset(page, page_size)
        conditions = []
        if device_id is not None:
            await self._managed_device(device_id)
            conditions.append(DeviceMaintenancePlan.device_id == device_id)
        if active is not None:
            conditions.append(DeviceMaintenancePlan.active.is_(active))
        scope = college_scope(self.principal)
        if scope is not None:
            conditions.append(DeviceMaintenancePlan.college_id == scope)
        if not self.principal.is_system_admin:
            conditions.append(
                DeviceMaintenancePlan.device_id.in_(
                    manageable_device_ids_statement(self.principal)
                )
            )
        id_query = select(DeviceMaintenancePlan.id)
        count_query = select(func.count(DeviceMaintenancePlan.id))
        total = int(await self.session.scalar(count_query.where(*conditions)) or 0)
        page_ids = delayed_page_ids(
            id_query.where(*conditions),
            DeviceMaintenancePlan.id,
            page=page,
            page_size=page_size,
        )
        plans = list(
            (
                await self.session.scalars(
                    select(DeviceMaintenancePlan)
                    .join(page_ids, page_ids.c.id == DeviceMaintenancePlan.id)
                    .options(selectinload(DeviceMaintenancePlan.device))
                    .order_by(DeviceMaintenancePlan.id.desc())
                )
            ).all()
        )
        pages, truncated = page_metadata(total, page_size)
        warnings = await ReservationService(self.session, self.principal)._maintenance_warnings(
            list({plan.device_id for plan in plans})
        )
        items = [await self._plan_data(plan, warnings) for plan in plans]
        return MaintenancePlanPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            truncated=truncated,
        )

    async def create_plan(
        self,
        device_id: int,
        payload: MaintenancePlanWrite,
    ) -> MaintenancePlanData:
        device = await self._managed_device(device_id, lock=True)
        if payload.active:
            await self._check_downtime_conflicts(
                device.id,
                payload.downtime_start,
                payload.downtime_end,
            )
        now = utcnow_naive()
        plan = DeviceMaintenancePlan(
            device_id=device.id,
            college_id=device.college_id,
            plan_type=payload.plan_type,
            title=payload.title,
            interval_value=payload.interval_value,
            interval_unit=payload.interval_unit,
            due_date=payload.due_date,
            downtime_start=payload.downtime_start,
            downtime_end=payload.downtime_end,
            active=payload.active,
            created_by=self.principal.user_id,
            updated_by=self.principal.user_id,
            created_at=now,
            updated_at=now,
        )
        plan.device = device
        self.session.add(plan)
        await self.session.flush()
        if plan.active:
            self._schedule_due_notification(plan)
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=device.college_id,
            action="MAINTENANCE_PLAN_CREATE",
            target_type="MAINTENANCE_PLAN",
            target_id=plan.id,
            detail={
                "device_id": device.id,
                "plan_type": plan.plan_type,
                "due_date": plan.due_date.isoformat(),
            },
        )
        enqueue_catalog_cache_bump(self.session, device.college_id)
        await self.session.commit()
        if self.app is not None:
            await sync_catalog_cache_bump(self.app, device.college_id)
        return await self.get_plan(plan.id)

    async def get_plan(self, plan_id: int) -> MaintenancePlanData:
        plan = await self._managed_plan(plan_id)
        return await self._plan_data(plan)

    async def update_plan(
        self,
        plan_id: int,
        payload: MaintenancePlanWrite,
    ) -> MaintenancePlanData:
        # Keep the same device -> plan lock order used by reservation writes.
        # The initial read is only to discover the immutable device_id; the
        # locked device check below is the authoritative authorization check.
        plan = await self._managed_plan(plan_id)
        device = await self._managed_device(plan.device_id, lock=True)
        plan = await self._managed_plan(plan_id, lock=True)
        if plan.plan_type != payload.plan_type:
            existing_record_id = await self.session.scalar(
                select(DeviceMaintenanceRecord.id)
                .where(DeviceMaintenanceRecord.plan_id == plan.id)
                .limit(1)
            )
            if existing_record_id is not None or plan.due_notice_sent_at is not None:
                raise ApiError(
                    "MAINTENANCE_PLAN_TYPE_IMMUTABLE",
                    "维护计划已有执行记录或已发送到期提醒，不能修改计划类型；请新建对应类型的计划",
                    409,
                )
        downtime_changed = (
            plan.downtime_start != payload.downtime_start
            or plan.downtime_end != payload.downtime_end
        )
        if payload.active and (not plan.active or downtime_changed):
            await self._check_downtime_conflicts(
                device.id,
                payload.downtime_start,
                payload.downtime_end,
            )
        due_changed = plan.due_date != payload.due_date
        previous_active = plan.active
        plan.plan_type = payload.plan_type
        plan.title = payload.title
        plan.interval_value = payload.interval_value
        plan.interval_unit = payload.interval_unit
        plan.due_date = payload.due_date
        plan.downtime_start = payload.downtime_start
        plan.downtime_end = payload.downtime_end
        plan.active = payload.active
        plan.updated_by = self.principal.user_id
        plan.updated_at = utcnow_naive()
        if due_changed:
            plan.due_notice_sent_at = None
        if plan.active and (due_changed or not previous_active):
            self._schedule_due_notification(plan)
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=device.college_id,
            action="MAINTENANCE_PLAN_UPDATE",
            target_type="MAINTENANCE_PLAN",
            target_id=plan.id,
            detail={
                "plan_type": plan.plan_type,
                "due_date": plan.due_date.isoformat(),
                "active": plan.active,
            },
        )
        enqueue_catalog_cache_bump(self.session, device.college_id)
        await self.session.commit()
        if self.app is not None:
            await sync_catalog_cache_bump(self.app, device.college_id)
        return await self.get_plan(plan.id)

    async def list_records(
        self,
        plan_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> MaintenanceRecordPage:
        plan = await self._managed_plan(plan_id)
        page_offset(page, page_size)
        id_query = select(DeviceMaintenanceRecord.id).where(
            DeviceMaintenanceRecord.plan_id == plan.id
        )
        total = int(
            await self.session.scalar(
                select(func.count(DeviceMaintenanceRecord.id)).where(
                    DeviceMaintenanceRecord.plan_id == plan.id
                )
            )
            or 0
        )
        page_ids = delayed_page_ids(
            id_query,
            DeviceMaintenanceRecord.id,
            page=page,
            page_size=page_size,
        )
        records = list(
            (
                await self.session.scalars(
                    select(DeviceMaintenanceRecord)
                    .join(page_ids, page_ids.c.id == DeviceMaintenanceRecord.id)
                    .options(
                        selectinload(DeviceMaintenanceRecord.evidence_asset),
                        selectinload(DeviceMaintenanceRecord.performer),
                    )
                    .order_by(DeviceMaintenanceRecord.id.desc())
                )
            ).all()
        )
        pages, truncated = page_metadata(total, page_size)
        return MaintenanceRecordPage(
            items=[await self._record_data(record) for record in records],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            truncated=truncated,
        )

    async def complete_cycle(
        self,
        plan_id: int,
        payload: MaintenanceRecordCreate,
        *,
        idempotency_key: str,
    ) -> MaintenanceRecordData:
        if not 8 <= len(idempotency_key) <= 128:
            raise ApiError("IDEMPOTENCY_KEY_INVALID", "幂等键长度必须为 8 到 128 个字符", 422)
        plan = await self._managed_plan(plan_id)
        device = await self._managed_device(plan.device_id, lock=True)
        plan = await self._managed_plan(plan_id, lock=True)
        asset: UploadAsset | None = None
        if payload.evidence_asset_token:
            asset = await self.session.scalar(
                select(UploadAsset)
                .where(
                    UploadAsset.asset_token == payload.evidence_asset_token,
                    UploadAsset.college_id == device.college_id,
                    UploadAsset.user_id == self.principal.user_id,
                )
                .with_for_update()
            )
            if asset is None:
                raise ApiError("EVIDENCE_NOT_FOUND", "维护凭证不存在或不属于当前学院", 404)
        if plan.plan_type in REQUIRED_EVIDENCE_TYPES and asset is None:
            raise ApiError(
                "MAINTENANCE_EVIDENCE_REQUIRED",
                "校准和安全检查完成时必须上传证书或记录",
                422,
            )
        request_hash = _request_hash(payload, asset.id if asset else None)
        previous = await self.session.scalar(
            select(DeviceMaintenanceRecord).where(
                DeviceMaintenanceRecord.plan_id == plan.id,
                DeviceMaintenanceRecord.idempotency_key == idempotency_key,
            )
        )
        if previous is not None:
            if previous.request_hash != request_hash:
                raise ApiError("IDEMPOTENCY_REUSED", "幂等键已用于另一份完成记录", 409)
            previous = await self.session.scalar(
                select(DeviceMaintenanceRecord)
                .options(
                    selectinload(DeviceMaintenanceRecord.evidence_asset),
                    selectinload(DeviceMaintenanceRecord.performer),
                )
                .where(DeviceMaintenanceRecord.id == previous.id)
            )
            return await self._record_data(previous)

        if payload.completed_date > date.today():
            raise ApiError("MAINTENANCE_DATE_INVALID", "完成日期不能晚于今天", 422)
        if payload.cycle_due_date != plan.due_date:
            raise ApiError("MAINTENANCE_CYCLE_CHANGED", "维护周期已变化，请刷新后重新提交", 409)

        previous_cycle = await self.session.scalar(
            select(DeviceMaintenanceRecord)
            .where(
                DeviceMaintenanceRecord.plan_id == plan.id,
                DeviceMaintenanceRecord.cycle_due_date == plan.due_date,
            )
            .order_by(DeviceMaintenanceRecord.id.desc())
            .limit(1)
        )
        if previous_cycle is not None:
            if previous_cycle.result != "FAILED" or previous_cycle.repair_report_id is None:
                raise ApiError(
                    "MAINTENANCE_CYCLE_ALREADY_COMPLETED",
                    "当前维护周期已记录完成，请刷新维护计划",
                    409,
                )
            repair_status = await self.session.scalar(
                select(RepairReport.status).where(
                    RepairReport.id == previous_cycle.repair_report_id
                )
            )
            if repair_status != "COMPLETED":
                raise ApiError(
                    "MAINTENANCE_REPAIR_NOT_COMPLETED",
                    "关联报修工单尚未闭环，不能提交维护复测记录",
                    409,
                )

        now = utcnow_naive()
        record = DeviceMaintenanceRecord(
            plan_id=plan.id,
            device_id=device.id,
            college_id=device.college_id,
            cycle_due_date=plan.due_date,
            completed_date=payload.completed_date,
            downtime_start=plan.downtime_start,
            downtime_end=plan.downtime_end,
            result=payload.result,
            notes=payload.notes,
            performed_by=self.principal.user_id,
            evidence_asset_id=asset.id if asset else None,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            created_at=now,
            evidence_asset=asset,
        )
        self.session.add(record)
        await self.session.flush()
        if payload.result == "PASSED":
            plan.due_date = add_interval(
                payload.completed_date,
                plan.interval_value,
                plan.interval_unit,
            )
            plan.downtime_start = None
            plan.downtime_end = None
            plan.due_notice_sent_at = None
            plan.updated_by = self.principal.user_id
            plan.updated_at = now
            if plan.active:
                self._schedule_due_notification(plan)
        else:
            report = await self._create_failed_maintenance_repair(
                plan, device, record, payload, now
            )
            record.repair_report_id = report.id
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=device.college_id,
            action=(
                "MAINTENANCE_COMPLETE_PASS"
                if payload.result == "PASSED"
                else "MAINTENANCE_COMPLETE_FAIL"
            ),
            target_type="MAINTENANCE_RECORD",
            target_id=record.id,
            detail={
                "plan_id": plan.id,
                "device_id": device.id,
                "result": payload.result,
                "cycle_due_date": payload.cycle_due_date.isoformat(),
            },
        )
        enqueue_catalog_cache_bump(self.session, device.college_id)
        await self.session.commit()
        if self.app is not None:
            await sync_catalog_cache_bump(self.app, device.college_id)
        stored = await self.session.scalar(
            select(DeviceMaintenanceRecord)
            .options(
                selectinload(DeviceMaintenanceRecord.evidence_asset),
                selectinload(DeviceMaintenanceRecord.performer),
            )
            .where(DeviceMaintenanceRecord.id == record.id)
        )
        return await self._record_data(stored)

    async def _create_failed_maintenance_repair(
        self,
        plan: DeviceMaintenancePlan,
        device: Device,
        record: DeviceMaintenanceRecord,
        payload: MaintenanceRecordCreate,
        now: datetime,
    ) -> RepairReport:
        report = RepairReport(
            college_id=device.college_id,
            device_id=device.id,
            reservation_id=None,
            reporter_id=self.principal.user_id,
            title=f"{plan.title}未通过，需要维修处理"[:200],
            description=(
                f"维护计划：{plan.title}\n"
                f"检查类型：{plan.plan_type}\n"
                f"完成日期：{payload.completed_date.isoformat()}\n"
                f"结果：未通过\n"
                f"情况说明：{payload.notes or '未填写'}"
            ),
            image_urls=None,
            status="PENDING",
            priority="IMPORTANT",
            response_due_at=now + timedelta(days=1),
            resolve_due_at=now
            + timedelta(
                days=max(
                    1,
                    int(
                        getattr(
                            getattr(getattr(self.app, "state", None), "settings", None),
                            "repair_sla_days",
                            {},
                        ).get("IMPORTANT", 2)
                    ),
                )
            ),
            created_at=now,
            updated_at=now,
        )
        report.device = device
        self.session.add(report)
        change_device_status(
            self.session,
            device,
            "MAINTENANCE",
            operator_id=self.principal.user_id,
            reason=f"维护计划“{plan.title}”检查未通过",
        )
        await self.session.flush()
        worklog = RepairWorklog(
            report_id=report.id,
            operator_id=self.principal.user_id,
            status="PENDING",
            content=f"系统根据维护计划“{plan.title}”检查未通过自动创建报修工单",
            created_at=now,
        )
        self.session.add(worklog)
        maintenance_kind = {
            "ROUTINE": "保养",
            "CALIBRATION": "校准",
            "SAFETY_CHECK": "安全检查",
        }.get(plan.plan_type, "维护检查")
        self.session.add(
            OutboxTask(
                task_key=f"repair:{report.id}:maintenance-failure",
                task_type="NOTIFICATION",
                aggregate_key=f"repair:{report.id}",
                college_id=report.college_id,
                payload={
                    "user_id": report.reporter_id,
                    "college_id": report.college_id,
                    "type": "REPAIR_UPDATE",
                    "title": f"{maintenance_kind}未通过，已创建报修工单",
                    "content": (
                        f"设备“{device.name}”的{maintenance_kind}计划“{plan.title}”未通过，"
                        f"工单 #{report.id} 已提交处理。"
                    ),
                    "related_id": report.id,
                    "related_type": "REPAIR",
                },
                execute_at=now,
            )
        )
        self.session.add(
            OutboxTask(
                task_key=f"repair:{report.id}:sla-response",
                task_type="REPAIR_SLA_REMINDER",
                aggregate_key=f"repair:{report.id}",
                college_id=report.college_id,
                payload={"report_id": report.id, "kind": "response"},
                execute_at=report.response_due_at or now,
            )
        )
        record.repair_report = report
        return report

    async def _record_data(self, record: DeviceMaintenanceRecord) -> MaintenanceRecordData:
        evidence = record.evidence_asset
        performer = record.performer
        return MaintenanceRecordData(
            id=record.id,
            plan_id=record.plan_id,
            device_id=record.device_id,
            college_id=record.college_id,
            cycle_due_date=record.cycle_due_date,
            completed_date=record.completed_date,
            downtime_start=record.downtime_start,
            downtime_end=record.downtime_end,
            result=record.result,  # type: ignore[arg-type]
            notes=record.notes,
            performed_by=record.performed_by,
            performed_by_name=(performer.real_name or performer.username) if performer else None,
            evidence_asset_token=evidence.asset_token if evidence else None,
            evidence_name=evidence.original_name if evidence else None,
            evidence_content_type=evidence.content_type if evidence else None,
            evidence_size_bytes=evidence.size_bytes if evidence else None,
            evidence_url=(
                f"{self._api_prefix()}/maintenance-evidence/{evidence.asset_token}"
                if evidence
                else None
            ),
            repair_report_id=record.repair_report_id,
            created_at=record.created_at,
        )
