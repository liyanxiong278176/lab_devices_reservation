from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import (
    AvailabilityDay,
    DeviceDetail,
    DeviceSummary,
    ReservationConflict,
    ReservationCreateData,
    ReservationData,
    ReservationDateSuggestion,
    ReservationDeviceSuggestion,
    ReservationPage,
    ReservationPlanRequest,
    ReservationPolicySnapshot,
    ReservationPreflightData,
    WaitlistConfirmationData,
    WaitlistData,
)
from app.application.lifecycle import append_audit, change_device_status
from app.application.reservation_policies import resolve_reservation_policy
from app.auth.security import Principal, college_scope
from app.core.errors import ApiError
from app.domain.reservation import ACTIVE_RESERVATION_STATUSES
from app.infrastructure.cache.cache import CacheService
from app.infrastructure.cache.invalidation import enqueue_catalog_cache_bump
from app.infrastructure.db.models import (
    College,
    CreditEvent,
    Device,
    DeviceDocument,
    DeviceDocumentAcknowledgement,
    DeviceHandover,
    DeviceMaintenancePlan,
    DeviceMaintenanceRecord,
    DeviceQualification,
    IdempotencyKey,
    Lab,
    OutboxTask,
    RepairReport,
    RepairWorklog,
    Reservation,
    ReservationBlackout,
    ReservationInspection,
    ReservationItem,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    UploadAsset,
    User,
)
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset

OPEN_REPAIR_STATUSES = ("PENDING", "PROCESSING", "RESOLVED")


@dataclass(frozen=True)
class DateBlock:
    reason: str
    is_maintenance: bool = False


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _date_at_end(value: date) -> datetime:
    return datetime.combine(value, time.max)


def request_hash(payload: ReservationPlanRequest) -> str:
    canonical = payload.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


async def _failed_maintenance_plan_ids(
    session: AsyncSession,
    plan_ids: list[int],
) -> set[int]:
    """Return plans whose latest recorded maintenance result is FAILED."""
    if not plan_ids:
        return set()
    ranked_records = (
        select(
            DeviceMaintenanceRecord.plan_id.label("plan_id"),
            DeviceMaintenanceRecord.result.label("result"),
            func.row_number()
            .over(
                partition_by=DeviceMaintenanceRecord.plan_id,
                order_by=(
                    DeviceMaintenanceRecord.created_at.desc(),
                    DeviceMaintenanceRecord.id.desc(),
                ),
            )
            .label("record_rank"),
        )
        .where(DeviceMaintenanceRecord.plan_id.in_(plan_ids))
        .subquery()
    )
    return set(
        (
            await session.scalars(
                select(ranked_records.c.plan_id).where(
                    ranked_records.c.record_rank == 1,
                    ranked_records.c.result == "FAILED",
                )
            )
        ).all()
    )


def _device_summary(device: Device, maintenance_warning: str | None = None) -> DeviceSummary:
    return DeviceSummary(
        id=device.id,
        name=device.name,
        status=device.status,
        brand=device.brand,
        model=device.model,
        specs=device.specs,
        image_url=device.image_url,
        category_id=device.category_id,
        category_name=device.category.name if device.category else None,
        lab_id=device.lab_id,
        lab_name=device.lab.name if device.lab else None,
        college_id=device.college_id,
        college_name=device.college.name if device.college else None,
        need_approval=device.need_approval,
        max_reservation_days=device.max_reservation_days,
        tags=device.tags,
        accessory_checklist=device.accessory_checklist or [],
        asset_code=device.asset_code,
        serial_number=device.serial_number,
        purchase_date=device.purchase_date,
        warranty_until=device.warranty_until,
        allow_external_loan=device.allow_external_loan,
        risk_level=device.risk_level,
        requires_safety_ack=device.requires_safety_ack,
        requires_qualification=device.requires_qualification,
        max_advance_days=device.max_advance_days,
        maintenance_warning=maintenance_warning,
    )


def _reservation_data(reservation: Reservation) -> ReservationData:
    user = reservation.__dict__.get("user")
    inspections = reservation.__dict__.get("inspections") or []
    inspection = inspections[-1] if inspections else None
    handover = reservation.__dict__.get("handover")
    device = reservation.device
    lab = device.__dict__.get("lab") if device else None
    handover_status = handover.status if handover else reservation.handover_status
    safety_acknowledged = bool(reservation.safety_acknowledged_at)
    return ReservationData(
        id=reservation.id,
        device_id=reservation.device_id,
        device_name=device.name if device else "",
        user_id=reservation.user_id,
        username=user.username if user else None,
        real_name=user.real_name if user else None,
        purpose=reservation.purpose,
        purpose_category=reservation.purpose_category or "OTHER",
        project_reference=reservation.project_reference,
        start_date=reservation.start_date,
        end_date=reservation.end_date,
        # ReservationItem is the live occupancy index and is deleted when a
        # reservation completes. Preserve historical dates from the immutable
        # range so completed reservations do not become zero-day records.
        dates=[
            reservation.start_date + timedelta(days=offset)
            for offset in range((reservation.end_date - reservation.start_date).days + 1)
        ],
        status=reservation.status,
        batch_id=reservation.batch_id,
        need_approval=device.need_approval if device else False,
        created_at=reservation.created_at,
        check_in_at=reservation.check_in_at,
        check_out_at=reservation.check_out_at,
        reject_reason=reservation.reject_reason,
        inspection_condition=inspection.condition if inspection else None,
        inspection_note=inspection.note if inspection else None,
        device_asset_code=device.asset_code if device else None,
        device_lab_name=lab.name if lab else None,
        requires_handover=handover_status not in {"NOT_REQUIRED", "CANCELLED"},
        handover_status=handover_status,
        safety_required=bool(device and device.requires_safety_ack),
        safety_acknowledged=safety_acknowledged,
        safety_document_version=reservation.safety_document_version,
        handover_image_urls=list(handover.handover_image_urls or []) if handover else [],
        return_image_urls=(
            list(handover.return_image_urls or [])
            if handover
            else list(inspection.image_urls or [])
            if inspection
            else []
        ),
        accessory_snapshot=list(handover.accessory_snapshot or []) if handover else [],
        handover_checklist=list(handover.handover_checklist or []) if handover else [],
        return_checklist=list(handover.return_checklist or []) if handover else [],
        fault_repair_id=(
            reservation.fault_repair.id
            if "fault_repair" in reservation.__dict__ and reservation.fault_repair
            else None
        ),
    )


class ReservationService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        max_days: int = 31,
        credit_block_threshold: int = 60,
        credit_block_days: int = 7,
        advance_days: int = 30,
        manager_advance_days: int = 90,
        cache: CacheService | None = None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.max_days = max_days
        self.credit_block_threshold = credit_block_threshold
        self.credit_block_days = credit_block_days
        self.advance_days = advance_days
        self.manager_advance_days = manager_advance_days
        self.cache = cache

    def _college_id(self) -> int | None:
        return college_scope(self.principal)

    async def _ensure_handover_record(
        self,
        reservation: Reservation,
        *,
        status: str,
        reservation_is_new: bool = False,
        now: datetime | None = None,
        note: str | None = None,
    ) -> DeviceHandover:
        timestamp = now or utcnow_naive()
        # A newly-created reservation cannot already have a handover row.
        # Avoid locking a missing key in the unique reservation_id index:
        # under InnoDB REPEATABLE READ, concurrent missing-row locking reads
        # can take compatible gap locks and then deadlock when both insert.
        handover = None
        if not reservation_is_new:
            handover = await self.session.scalar(
                select(DeviceHandover)
                .where(DeviceHandover.reservation_id == reservation.id)
                .with_for_update()
            )
        if handover is None:
            handover = DeviceHandover(
                reservation_id=reservation.id,
                device_id=reservation.device_id,
                user_id=reservation.user_id,
                college_id=reservation.college_id,
                status=status,
                handover_note=note,
                accessory_snapshot=list(reservation.device.accessory_checklist or []),
                created_at=reservation.created_at or timestamp,
                updated_at=timestamp,
            )
            self.session.add(handover)
        else:
            handover.status = status
            handover.updated_at = timestamp
            if note is not None:
                handover.handover_note = note
            if handover.accessory_snapshot is None:
                handover.accessory_snapshot = list(reservation.device.accessory_checklist or [])
        reservation.handover = handover
        reservation.handover_status = status
        return handover

    async def _set_handover_status(
        self,
        reservation: Reservation,
        status: str,
        *,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or utcnow_naive()
        handover = await self.session.scalar(
            select(DeviceHandover).where(DeviceHandover.reservation_id == reservation.id)
        )
        if handover is not None:
            handover.status = status
            handover.updated_at = timestamp
        reservation.handover_status = status

    async def _load_device(self, device_id: int) -> Device:
        stmt = (
            select(Device)
            .options(
                selectinload(Device.lab),
                selectinload(Device.college),
                selectinload(Device.category),
            )
            .where(Device.id == device_id, Device.status != "DELETED")
        )
        scope = self._college_id()
        if scope is not None:
            stmt = stmt.where(Device.college_id == scope)
        device = await self.session.scalar(stmt)
        if device is None:
            raise ApiError("DEVICE_NOT_FOUND", "设备不存在或不属于当前学院", 404)
        if device.lab and device.lab.college_id not in (None, device.college_id):
            raise ApiError("TENANT_DATA_INVALID", "设备所属实验室与学院不一致", 409)
        return device

    async def list_devices(
        self,
        *,
        search: str | None = None,
        lab_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        include_meta: bool = False,
    ) -> tuple[list[DeviceSummary], int] | tuple[list[DeviceSummary], int, int, bool]:
        if not self.principal.has_permission("device:read"):
            raise ApiError("FORBIDDEN", "当前账号没有查看设备的权限", 403)
        page_offset(page, page_size)
        if self.cache is not None and not self.principal.is_system_admin:
            scope = self._college_id()
            scope_key = "global" if scope is None else f"college:{scope}"
            viewer_key = (
                f"manager:{self.principal.user_id}"
                if self.principal.is_lab_admin and not self.principal.is_system_admin
                else "member"
            )
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "search": search,
                        "lab_id": lab_id,
                        "status": status,
                        "page": page,
                        "page_size": page_size,
                        "viewer": viewer_key,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:24]
            try:
                version = await self.cache.version(scope_key)
                key = f"lab:v2:catalog:devices:{scope_key}:v{version}:{fingerprint}"

                async def load() -> dict[str, object]:
                    items, total, pages, truncated = await self._list_devices_from_db(
                        search=search,
                        lab_id=lab_id,
                        status=status,
                        page=page,
                        page_size=page_size,
                    )
                    return {
                        "items": [item.model_dump(mode="json") for item in items],
                        "total": total,
                        "pages": pages,
                        "truncated": truncated,
                    }

                raw = await self.cache.get_or_set_json(key, load)
                result = (
                    [DeviceSummary.model_validate(item) for item in raw.get("items", [])],
                    int(raw.get("total", 0)),
                    int(raw.get("pages", 0)),
                    bool(raw.get("truncated", False)),
                )
                return result if include_meta else result[:2]
            except Exception:
                # Cache is an optimization. Any serialization or Redis issue
                # falls back to the authoritative query.
                pass
        result = await self._list_devices_from_db(
            search=search,
            lab_id=lab_id,
            status=status,
            page=page,
            page_size=page_size,
        )
        return result if include_meta else result[:2]

    async def _list_devices_from_db(
        self,
        *,
        search: str | None,
        lab_id: int | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[DeviceSummary], int, int, bool]:
        page_offset(page, page_size)
        scope = self._college_id()
        conditions = [Device.status != "DELETED"]
        if scope is not None:
            conditions.append(Device.college_id == scope)
        if search:
            like = f"%{search.strip()}%"
            conditions.append(
                or_(
                    Device.name.like(like),
                    Device.model.like(like),
                    Device.asset_code.like(like),
                )
            )
        if lab_id is not None:
            conditions.append(Device.lab_id == lab_id)
        if status:
            conditions.append(Device.status == status)
        id_stmt = select(Device.id).select_from(Device)
        count_stmt = select(func.count(Device.id)).select_from(Device)
        if self.principal.is_lab_admin and not self.principal.is_system_admin:
            id_stmt = id_stmt.outerjoin(Lab, Lab.id == Device.lab_id).join(
                College,
                College.id == Device.college_id,
            )
            count_stmt = count_stmt.outerjoin(Lab, Lab.id == Device.lab_id).join(
                College,
                College.id == Device.college_id,
            )
            conditions.append(
                or_(
                    Lab.manager_id == self.principal.user_id,
                    College.manager_id == self.principal.user_id,
                )
            )
        total = int(await self.session.scalar(count_stmt.where(*conditions)) or 0)
        page_ids = delayed_page_ids(
            id_stmt.where(*conditions),
            Device.id,
            page=page,
            page_size=page_size,
        )
        stmt = (
            select(Device)
            .join(page_ids, page_ids.c.id == Device.id)
            .options(
                selectinload(Device.lab),
                selectinload(Device.college),
                selectinload(Device.category),
            )
            .order_by(Device.id.desc())
        )
        devices = list((await self.session.scalars(stmt)).all())
        maintenance_warnings = await self._maintenance_warnings([device.id for device in devices])
        pages, truncated = page_metadata(total, page_size)
        return (
            [_device_summary(device, maintenance_warnings.get(device.id)) for device in devices],
            total,
            pages,
            truncated,
        )

    async def get_device(self, device_id: int) -> DeviceDetail:
        if not self.principal.has_permission("device:read"):
            raise ApiError("FORBIDDEN", "当前账号没有查看设备的权限", 403)
        device = await self._load_device(device_id)
        warnings = await self._maintenance_warnings([device.id])
        return DeviceDetail(
            **_device_summary(device, warnings.get(device.id)).model_dump(),
            description=device.description,
            location=device.lab.location if device.lab else None,
        )

    async def availability(
        self,
        device_id: int,
        start_date: date,
        end_date: date,
    ) -> list[AvailabilityDay]:
        if not self.principal.has_permission("device:read"):
            raise ApiError("FORBIDDEN", "当前账号没有查看设备的权限", 403)
        if end_date < start_date:
            raise ApiError("DATE_RANGE_INVALID", "结束日期不能早于开始日期", 422)
        if (end_date - start_date).days + 1 > self.max_days:
            raise ApiError("DATE_RANGE_TOO_LARGE", f"单次最多查询 {self.max_days} 天", 422)
        device = await self._load_device(device_id)
        occupied = await self._occupied(
            device.id,
            [
                date.fromordinal(value)
                for value in range(start_date.toordinal(), end_date.toordinal() + 1)
            ],
        )
        blocked_dates = await self._blocked_date_details(
            device,
            [
                date.fromordinal(value)
                for value in range(start_date.toordinal(), end_date.toordinal() + 1)
            ],
        )
        blocked = device.status in {"MAINTENANCE", "DISABLED", "RETIRED", "OFFLINE"}
        result: list[AvailabilityDay] = []
        current = start_date
        while current <= end_date:
            row = occupied.get(current)
            date_block = blocked_dates.get(current)
            result.append(
                AvailabilityDay(
                    date=current,
                    available=row is None and date_block is None and not blocked,
                    reservation_id=row[0] if row else None,
                    status=(
                        row[1]
                        if row
                        else (
                            "MAINTENANCE_RESTRICTION"
                            if date_block is not None and date_block.is_maintenance
                            else "BLACKOUT"
                            if date_block is not None
                            else device.status
                            if blocked
                            else None
                        )
                    ),
                    reason=(
                        date_block.reason
                        if date_block is not None
                        else (f"设备状态为 {device.status}" if blocked else None)
                    ),
                )
            )
            current += timedelta(days=1)
        return result

    async def preflight(self, plan: ReservationPlanRequest) -> ReservationPreflightData:
        if not self.principal.has_permission("reservation:create"):
            raise ApiError("FORBIDDEN", "当前账号没有创建预约的权限", 403)
        device = await self._load_device(plan.device_id)
        dates = plan.requested_dates()
        policy = await resolve_reservation_policy(
            self.session,
            self.principal,
            device,
            default_max_booking_days=self.max_days,
            default_student_advance_days=self.advance_days,
            default_manager_advance_days=self.manager_advance_days,
        )
        self._validate_dates(
            dates,
            policy.max_booking_days,
            policy.max_advance_days,
            plan.reservation_segments(),
        )
        access = await self._access_snapshot(device, coverage_until=max(dates))
        occupied = await self._occupied(device.id, dates)
        blackout = await self._blocked_dates(device, dates)
        conflicts = [
            ReservationConflict(
                date=current,
                reason=(
                    "该日期正在为候补用户保留" if row[1] == "WAITLIST_HOLD" else "设备已有有效预约"
                ),
                reservation_id=row[0] or None,
                status=row[1],
            )
            for current, row in sorted(occupied.items())
        ]
        conflicts.extend(
            ReservationConflict(date=current, reason=reason)
            for current, reason in sorted(blackout.items())
            if current not in occupied
        )
        if device.status in {"MAINTENANCE", "DISABLED", "RETIRED", "OFFLINE"}:
            conflicts = [
                ReservationConflict(date=current, reason=f"设备状态为 {device.status}")
                for current in dates
            ]
        conflict_dates = {item.date for item in conflicts}
        same_device_suggestions: list[ReservationDateSuggestion] = []
        similar_device_suggestions: list[ReservationDeviceSuggestion] = []
        if conflicts:
            (
                same_device_suggestions,
                similar_device_suggestions,
            ) = await self._reservation_suggestions(
                device,
                dates,
                max_advance_days=policy.max_advance_days,
            )
        return ReservationPreflightData(
            device=_device_summary(
                device,
                (await self._maintenance_warnings([device.id])).get(device.id),
            ),
            requested_dates=dates,
            available_dates=[current for current in dates if current not in conflict_dates],
            conflicts=conflicts,
            all_available=not conflicts,
            effective_policy=ReservationPolicySnapshot(
                user_category=policy.user_category,  # type: ignore[arg-type]
                max_booking_days=policy.max_booking_days,
                max_advance_days=policy.max_advance_days,
                approval_required=policy.approval_required,
            ),
            safety_required=access["safety_required"],
            safety_acknowledged=access["safety_acknowledged"],
            qualification_required=access["qualification_required"],
            qualification_approved=access["qualification_approved"],
            safety_document_version=access["safety_document_version"],
            qualification_valid_until=access["qualification_valid_until"],
            same_device_suggestions=same_device_suggestions,
            similar_device_suggestions=similar_device_suggestions,
        )

    def _validate_dates(
        self,
        dates: list[date],
        max_booking_days: int,
        max_advance_days: int,
        reservation_segments: list[list[date]],
    ) -> None:
        if not dates:
            raise ApiError("DATE_RANGE_EMPTY", "至少选择一个预约日期", 422)
        longest_contiguous_segment = max(map(len, reservation_segments))
        if longest_contiguous_segment > max_booking_days:
            raise ApiError(
                "DATE_RANGE_TOO_LARGE",
                f"该设备单次连续预约最多 {max_booking_days} 天",
                422,
            )
        if min(dates) < date.today():
            raise ApiError("DATE_IN_PAST", "不能预约过去的日期", 422)
        latest_allowed = date.today() + timedelta(days=max_advance_days)
        if max(dates) > latest_allowed:
            raise ApiError(
                "DATE_TOO_FAR",
                f"该设备最多只能提前 {max_advance_days} 个自然日预约",
                422,
                data={"latest_allowed_date": latest_allowed},
            )

    async def _access_snapshot(
        self,
        device: Device,
        *,
        coverage_until: date | None = None,
    ) -> dict[str, object]:
        required_documents = list(
            (
                await self.session.scalars(
                    select(DeviceDocument)
                    .where(
                        DeviceDocument.device_id == device.id,
                        DeviceDocument.active.is_(True),
                        DeviceDocument.requires_ack.is_(True),
                    )
                    .order_by(DeviceDocument.document_type, DeviceDocument.id.desc())
                )
            ).all()
        )
        latest_documents: list[DeviceDocument] = []
        seen_types: set[str] = set()
        for document in required_documents:
            if document.document_type not in seen_types:
                latest_documents.append(document)
                seen_types.add(document.document_type)
        acknowledged_ids: set[int] = set()
        if latest_documents:
            acknowledged_ids = set(
                (
                    await self.session.scalars(
                        select(DeviceDocumentAcknowledgement.document_id).where(
                            DeviceDocumentAcknowledgement.user_id == self.principal.user_id,
                            DeviceDocumentAcknowledgement.document_id.in_(
                                [document.id for document in latest_documents]
                            ),
                        )
                    )
                ).all()
            )
        safety_required = bool(device.requires_safety_ack or latest_documents)
        safety_acknowledged = bool(latest_documents) and len(acknowledged_ids) == len(
            latest_documents
        )
        if not safety_required:
            safety_acknowledged = True
        qualification_required = bool(
            device.requires_qualification or device.risk_level in {"HIGH", "CRITICAL"}
        )
        qualification_approved = False
        qualification_valid_until: date | None = None
        if qualification_required:
            qualification = await self.session.scalar(
                select(DeviceQualification)
                .where(
                    DeviceQualification.device_id == device.id,
                    DeviceQualification.user_id == self.principal.user_id,
                    DeviceQualification.status == "APPROVED",
                )
                .order_by(DeviceQualification.reviewed_at.desc(), DeviceQualification.id.desc())
            )
            if qualification is not None:
                qualification_valid_until = qualification.valid_until
                required_until = coverage_until or date.today()
                qualification_approved = (
                    qualification.valid_until is None or qualification.valid_until >= required_until
                )
        latest_version = latest_documents[0].version if latest_documents else None
        return {
            "safety_required": safety_required,
            "safety_acknowledged": safety_acknowledged,
            "qualification_required": qualification_required,
            "qualification_approved": qualification_approved,
            "qualification_valid_until": qualification_valid_until,
            "safety_document_version": latest_version,
        }

    async def access_snapshot(self, device_id: int) -> dict[str, object]:
        return await self._access_snapshot(await self._load_device(device_id))

    async def _occupied(self, device_id: int, dates: list[date]) -> dict[date, tuple[int, str]]:
        if not dates:
            return {}
        conditions = [
            ReservationItem.device_id == device_id,
            ReservationItem.reservation_date.in_(dates),
            Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
        ]
        scope = self._college_id()
        if scope is not None:
            conditions.append(Reservation.college_id == scope)
        stmt = (
            select(ReservationItem.reservation_date, Reservation.id, Reservation.status)
            .join(Reservation, Reservation.id == ReservationItem.reservation_id)
            .where(*conditions)
        )
        occupied = {
            row[0]: (int(row[1]), str(row[2])) for row in (await self.session.execute(stmt)).all()
        }
        held_dates = (
            await self.session.scalars(
                select(ReservationWaitlistOffer.reservation_date).where(
                    ReservationWaitlistOffer.device_id == device_id,
                    ReservationWaitlistOffer.reservation_date.in_(dates),
                    ReservationWaitlistOffer.expires_at > utcnow_naive(),
                )
            )
        ).all()
        for held_date in held_dates:
            occupied.setdefault(held_date, (0, "WAITLIST_HOLD"))
        return occupied

    async def _reservation_suggestions(
        self,
        device: Device,
        requested_dates: list[date],
        *,
        max_advance_days: int,
    ) -> tuple[list[ReservationDateSuggestion], list[ReservationDeviceSuggestion]]:
        if not requested_dates:
            return [], []
        today = date.today()
        horizon = today + timedelta(days=max_advance_days)
        duration = len(requested_dates)
        earliest = max(today + timedelta(days=1), max(requested_dates) + timedelta(days=1))
        last_start = horizon - timedelta(days=duration - 1)
        date_suggestions: list[ReservationDateSuggestion] = []
        if (
            device.status not in {"MAINTENANCE", "DISABLED", "RETIRED", "OFFLINE"}
            and earliest <= last_start
        ):
            candidate_dates = [
                current
                for ordinal in range(
                    earliest.toordinal(),
                    (last_start + timedelta(days=duration - 1)).toordinal() + 1,
                )
                for current in [date.fromordinal(ordinal)]
            ]
            occupied = await self._occupied(device.id, candidate_dates)
            blocked = await self._blocked_dates(device, candidate_dates)
            cursor = earliest
            while cursor <= last_start and len(date_suggestions) < 3:
                window = [cursor + timedelta(days=offset) for offset in range(duration)]
                if all(day not in occupied and day not in blocked for day in window):
                    date_suggestions.append(
                        ReservationDateSuggestion(start_date=window[0], end_date=window[-1])
                    )
                cursor += timedelta(days=1)

        similar: list[ReservationDeviceSuggestion] = []
        if device.category_id is not None and device.college_id is not None:
            candidates = list(
                await self.session.scalars(
                    select(Device)
                    .options(selectinload(Device.category), selectinload(Device.lab))
                    .where(
                        Device.id != device.id,
                        Device.college_id == device.college_id,
                        Device.category_id == device.category_id,
                        Device.status == "IDLE",
                    )
                    .order_by(Device.id)
                    .limit(30)
                )
            )
            for candidate in candidates:
                if await self._occupied(candidate.id, requested_dates):
                    continue
                if await self._blocked_dates(candidate, requested_dates):
                    continue
                similar.append(
                    ReservationDeviceSuggestion(
                        device_id=candidate.id,
                        name=candidate.name,
                        lab_name=candidate.lab.name if candidate.lab else None,
                        category_name=candidate.category.name if candidate.category else None,
                    )
                )
                if len(similar) == 4:
                    break
        return date_suggestions, similar

    async def _blocked_dates(
        self,
        device: Device,
        dates: list[date],
    ) -> dict[date, str]:
        details = await self._blocked_date_details(device, dates)
        return {blocked_date: block.reason for blocked_date, block in details.items()}

    async def _blocked_date_details(
        self,
        device: Device,
        dates: list[date],
    ) -> dict[date, DateBlock]:
        if not dates:
            return {}
        return (
            await self._blocked_dates_for_devices(
                {device.id: device},
                {device.id: set(dates)},
            )
        ).get(device.id, {})

    async def _blocked_dates_for_devices(
        self,
        devices_by_id: dict[int, Device],
        dates_by_device: dict[int, set[date]],
    ) -> dict[int, dict[date, DateBlock]]:
        """Resolve blackout and maintenance restrictions with bounded query count."""
        requested_devices = {
            device_id: devices_by_id[device_id]
            for device_id, dates in dates_by_device.items()
            if dates and device_id in devices_by_id
        }
        if not requested_devices:
            return {}

        all_dates = set().union(*(dates_by_device[device_id] for device_id in requested_devices))
        device_ids = set(requested_devices)
        lab_ids = {
            device.lab_id
            for device in requested_devices.values()
            if device.lab_id is not None
        }
        college_ids = {device.college_id for device in requested_devices.values()}
        scope_filters = [
            and_(
                ReservationBlackout.scope_type == "DEVICE",
                ReservationBlackout.scope_id.in_(device_ids),
            ),
            and_(
                ReservationBlackout.scope_type == "LAB",
                ReservationBlackout.scope_id.in_(lab_ids),
            ),
            and_(
                ReservationBlackout.scope_type == "COLLEGE",
                ReservationBlackout.scope_id.in_(college_ids),
            ),
        ]
        blackout_rows = list(
            (
                await self.session.execute(
                    select(
                        ReservationBlackout.scope_type,
                        ReservationBlackout.scope_id,
                        ReservationBlackout.blocked_date,
                        ReservationBlackout.reason,
                    ).where(
                        ReservationBlackout.active.is_(True),
                        ReservationBlackout.blocked_date.in_(all_dates),
                        or_(*scope_filters),
                    )
                )
            ).all()
        )
        blackout_by_scope_date = {
            (row.scope_type, row.scope_id, row.blocked_date): DateBlock(str(row.reason))
            for row in blackout_rows
        }

        plans = list(
            (
                await self.session.scalars(
                    select(DeviceMaintenancePlan).where(
                        DeviceMaintenancePlan.device_id.in_(device_ids),
                    )
                )
            ).all()
        )
        plans_by_device: dict[int, list[DeviceMaintenancePlan]] = {}
        for plan in plans:
            plans_by_device.setdefault(plan.device_id, []).append(plan)
        failed_plan_ids = await _failed_maintenance_plan_ids(
            self.session, [plan.id for plan in plans]
        )

        blocked_by_device: dict[int, dict[date, DateBlock]] = {}
        today = date.today()
        for device_id, device in requested_devices.items():
            requested_dates = dates_by_device[device_id]
            blocked: dict[date, DateBlock] = {}
            for requested_date in requested_dates:
                for scope_type, scope_id in (
                    ("DEVICE", device.id),
                    ("LAB", device.lab_id),
                    ("COLLEGE", device.college_id),
                ):
                    if scope_id is None:
                        continue
                    reason = blackout_by_scope_date.get(
                        (scope_type, scope_id, requested_date)
                    )
                    if reason is not None:
                        blocked[requested_date] = reason
                        break

            critical_plans = [
                plan
                for plan in plans_by_device.get(device_id, [])
                if plan.plan_type in {"CALIBRATION", "SAFETY_CHECK"}
            ]
            for plan in plans_by_device.get(device_id, []):
                for requested_date in requested_dates:
                    if plan.id in failed_plan_ids:
                        blocked.setdefault(
                            requested_date,
                            DateBlock(f"{plan.title}未通过，设备暂不可预约", True),
                        )
                    elif plan.active and (
                        plan.downtime_start is not None
                        and plan.downtime_end is not None
                        and plan.downtime_start <= requested_date <= plan.downtime_end
                    ):
                        blocked.setdefault(
                            requested_date,
                            DateBlock(f"维护停机：{plan.title}", True),
                        )
                    elif (
                        plan.active
                        and plan in critical_plans
                        and today > plan.due_date
                        and requested_date >= today
                    ):
                        blocked.setdefault(
                            requested_date,
                            DateBlock(f"{plan.title}已逾期，设备暂不可预约", True),
                        )
            blocked_by_device[device_id] = blocked
        return blocked_by_device

    async def _maintenance_warnings(self, device_ids: list[int]) -> dict[int, str]:
        if not device_ids:
            return {}
        today = date.today()
        plans = list(
            (
                await self.session.scalars(
                    select(DeviceMaintenancePlan).where(
                        DeviceMaintenancePlan.device_id.in_(device_ids),
                    )
                )
            ).all()
        )
        if not plans:
            return {}
        failed_plan_ids = await _failed_maintenance_plan_ids(
            self.session,
            [plan.id for plan in plans],
        )
        warnings: dict[int, str] = {}
        for plan in plans:
            if plan.id in failed_plan_ids:
                warnings.setdefault(plan.device_id, f"{plan.title}未通过，设备暂不可预约")
            elif (
                plan.active
                and plan.plan_type in {"CALIBRATION", "SAFETY_CHECK"}
                and today > plan.due_date
            ):
                warnings.setdefault(plan.device_id, f"{plan.title}已逾期，设备暂不可预约")
        return warnings

    async def _validate_evidence_images(
        self,
        image_urls: list[str] | None,
        device: Device,
    ) -> list[str]:
        if not image_urls or not 1 <= len(image_urls) <= 6:
            raise ApiError("EVIDENCE_REQUIRED", "必须上传 1 至 6 张 JPG、PNG 或 WebP 现场照片", 422)
        tokens: list[str] = []
        normalized: list[str] = []
        for value in image_urls:
            match = re.fullmatch(r"(?:/api/v2)?/repair-uploads/([A-Za-z0-9_-]{20,})", value.strip())
            if match is None:
                raise ApiError("EVIDENCE_INVALID", "现场照片必须先上传到本系统", 422)
            token = match.group(1)
            if token in tokens:
                raise ApiError("EVIDENCE_DUPLICATE", "现场照片不能重复", 422)
            tokens.append(token)
            normalized.append(f"/api/v2/repair-uploads/{token}")
        asset_scope = UploadAsset.college_id == device.college_id
        if self.principal.is_system_admin:
            # System-admin uploads are intentionally tenant-neutral. They may
            # be attached to a resource in any college after authorization;
            # tenant-scoped users still must use an asset from their college.
            asset_scope = or_(asset_scope, UploadAsset.college_id.is_(None))
        assets = list(
            (
                await self.session.scalars(
                    select(UploadAsset)
                    .where(
                        UploadAsset.asset_token.in_(tokens),
                        UploadAsset.user_id == self.principal.user_id,
                        asset_scope,
                    )
                    .order_by(UploadAsset.id)
                    .with_for_update()
                )
            ).all()
        )
        by_token = {asset.asset_token: asset for asset in assets}
        if len(by_token) != len(tokens):
            raise ApiError("EVIDENCE_FORBIDDEN", "现场照片不存在、非本人上传或不属于本学院", 403)
        allowed = {"image/jpeg", "image/png", "image/webp"}
        if any(
            by_token[token].content_type not in allowed
            or by_token[token].size_bytes > 5 * 1024 * 1024
            for token in tokens
        ):
            raise ApiError("EVIDENCE_INVALID", "现场照片仅支持 5 MB 以内 JPG、PNG 或 WebP", 422)
        return normalized

    @staticmethod
    def _validated_checklist(
        expected: list[str] | None,
        supplied: list[object] | None,
    ) -> list[dict[str, object]]:
        expected_names = list(expected or [])
        values = [
            item.model_dump() if hasattr(item, "model_dump") else dict(item)
            for item in (supplied or [])
        ]
        names = [str(item.get("name", "")).strip() for item in values]
        if len(names) != len(set(names)) or set(names) != set(expected_names):
            raise ApiError("CHECKLIST_MISMATCH", "必须逐项核对设备当前配件清单", 422)
        return [
            {
                "name": name,
                "condition": str(item.get("condition", "NORMAL")),
                "note": str(item.get("note")).strip() if item.get("note") else None,
            }
            for name, item in zip(names, values, strict=True)
        ]

    @staticmethod
    def _effective_condition(
        requested: str,
        checklist: list[dict[str, object]],
    ) -> str:
        conditions = {requested, *(str(item["condition"]) for item in checklist)}
        if "MISSING" in conditions:
            return "MISSING"
        if "DAMAGED" in conditions:
            return "DAMAGED"
        return "NORMAL"

    async def _create_fault_repair(
        self,
        reservation: Reservation,
        *,
        phase: str,
        condition: str,
        note: str | None,
        image_urls: list[str],
        checklist: list[dict[str, object]],
        now: datetime,
    ) -> RepairReport:
        report = await self.session.scalar(
            select(RepairReport).where(RepairReport.reservation_id == reservation.id)
        )
        if report is not None:
            return report
        findings = [
            f"{item['name']}：{'损坏' if item['condition'] == 'DAMAGED' else '缺失'}"
            for item in checklist
            if item["condition"] != "NORMAL"
        ]
        reason = note.strip() if note and note.strip() else "；".join(findings)
        reason = reason or (
            "现场交接发现设备异常" if phase == "领用交接" else "归还验收发现设备异常"
        )
        report = RepairReport(
            college_id=reservation.college_id,
            device_id=reservation.device_id,
            reservation_id=reservation.id,
            reporter_id=reservation.user_id,
            title=f"预约 #{reservation.id} {phase}异常：{reservation.device.name}",
            description=(
                f"由预约履约自动生成。环节：{phase}；异常类型：{condition}；"
                f"说明：{reason}；预约日期：{reservation.start_date} 至 {reservation.end_date}。"
            ),
            image_urls=image_urls,
            status="PENDING",
            priority="IMPORTANT",
            response_due_at=now + timedelta(days=1),
            resolve_due_at=now + timedelta(days=3),
            created_at=now,
            updated_at=now,
        )
        self.session.add(report)
        await self.session.flush()
        self.session.add(
            RepairWorklog(
                report_id=report.id,
                operator_id=self.principal.user_id,
                status="PENDING",
                content=(
                    f"预约 #{reservation.id} 的{phase}发现 {condition} 异常，"
                    f"系统自动创建维修工单。{reason}"
                ),
                image_urls=image_urls,
                created_at=now,
            )
        )
        change_device_status(
            self.session,
            reservation.device,
            "MAINTENANCE",
            operator_id=self.principal.user_id,
            reason=f"预约 #{reservation.id}{phase}确认设备异常：{reason}",
        )
        enqueue_catalog_cache_bump(self.session, reservation.college_id)
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:fault:{phase}",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "RESERVATION_UPDATE",
                    "title": "设备异常，已转入维修",
                    "content": (
                        f"预约 #{reservation.id} 的{phase}确认设备异常，设备已暂停预约"
                        f"并自动生成维修单 #{report.id}。"
                        "请联系负责人取消预约或改约本学院其他设备。"
                    ),
                    "related_id": reservation.id,
                    "related_type": "RESERVATION",
                },
                execute_at=now,
            )
        )
        reservation.fault_repair = report
        return report

    async def join_waitlist(
        self,
        *,
        device_id: int,
        reservation_date: date,
        purpose: str,
        purpose_category: str = "OTHER",
        project_reference: str | None = None,
    ) -> WaitlistData:
        if not self.principal.has_permission("reservation:create"):
            raise ApiError("FORBIDDEN", "当前账号没有加入候补的权限", 403)
        device = await self._load_device(device_id)
        if reservation_date < date.today():
            raise ApiError("DATE_IN_PAST", "不能排队过去的日期", 422)
        if device.status in {"MAINTENANCE", "DISABLED", "RETIRED", "OFFLINE"}:
            raise ApiError("DEVICE_UNAVAILABLE", "当前设备状态不支持候补", 409)
        if not await self._occupied(device_id, [reservation_date]):
            raise ApiError("WAITLIST_NOT_NEEDED", "该日期当前可以直接预约", 409)
        if reservation_date in await self._blocked_dates(device, [reservation_date]):
            raise ApiError("DATE_BLOCKED", "该日期被设置为不可预约", 409)
        existing = await self.session.scalar(
            select(ReservationWaitlist).where(
                ReservationWaitlist.device_id == device_id,
                ReservationWaitlist.reservation_date == reservation_date,
                ReservationWaitlist.user_id == self.principal.user_id,
            )
        )
        if existing is not None and existing.status in {"WAITING", "OFFERED", "NOTIFIED"}:
            raise ApiError("WAITLIST_EXISTS", "你已经在该日期的候补队列中", 409)
        now = utcnow_naive()
        entry = existing or ReservationWaitlist(
            device_id=device_id,
            college_id=device.college_id,
            user_id=self.principal.user_id,
            reservation_date=reservation_date,
        )
        entry.purpose = purpose.strip()
        entry.purpose_category = purpose_category
        entry.project_reference = project_reference.strip() if project_reference else None
        entry.status = "WAITING"
        entry.notified_at = None
        entry.created_at = now
        self.session.add(entry)
        try:
            await self.session.flush()
            append_audit(
                self.session,
                user_id=self.principal.user_id,
                college_id=device.college_id,
                action="WAITLIST_JOIN",
                target_type="WAITLIST",
                target_id=entry.id,
                detail={
                    "device_id": device_id,
                    "reservation_date": reservation_date.isoformat(),
                },
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApiError("WAITLIST_EXISTS", "你已经提交过该日期候补申请", 409) from exc
        return WaitlistData(
            id=entry.id,
            device_id=entry.device_id,
            device_name=device.name,
            reservation_date=entry.reservation_date,
            purpose=entry.purpose,
            purpose_category=entry.purpose_category,
            project_reference=entry.project_reference,
            status=entry.status,
            created_at=entry.created_at,
        )

    async def list_waitlist(self) -> list[WaitlistData]:
        if not self.principal.has_permission("reservation:read:own"):
            raise ApiError("FORBIDDEN", "当前账号没有查看个人预约的权限", 403)
        conditions = [
            ReservationWaitlist.user_id == self.principal.user_id,
            ReservationWaitlist.status.in_(("WAITING", "OFFERED", "NOTIFIED")),
        ]
        scope = self._college_id()
        if scope is not None:
            conditions.append(ReservationWaitlist.college_id == scope)
        rows = list(
            (
                await self.session.execute(
                    select(ReservationWaitlist, Device.name)
                    .join(Device, Device.id == ReservationWaitlist.device_id)
                    .where(*conditions)
                    .order_by(ReservationWaitlist.id.desc())
                )
            ).all()
        )
        offers = (
            list(
                (
                    await self.session.scalars(
                        select(ReservationWaitlistOffer).where(
                            ReservationWaitlistOffer.waitlist_id.in_(
                                [entry.id for entry, _ in rows]
                            )
                        )
                    )
                ).all()
            )
            if rows
            else []
        )
        offer_by_entry = {offer.waitlist_id: offer for offer in offers}
        return [
            WaitlistData(
                id=entry.id,
                device_id=entry.device_id,
                device_name=name,
                reservation_date=entry.reservation_date,
                purpose=entry.purpose,
                purpose_category=entry.purpose_category,
                project_reference=entry.project_reference,
                status=entry.status,
                created_at=entry.created_at,
                offered_until=(
                    offer_by_entry[entry.id].expires_at if entry.id in offer_by_entry else None
                ),
            )
            for entry, name in rows
        ]

    async def cancel_waitlist(self, entry_id: int) -> None:
        if not self.principal.has_permission("reservation:cancel"):
            raise ApiError("FORBIDDEN", "当前账号没有取消候补的权限", 403)
        entry = await self.session.scalar(
            select(ReservationWaitlist)
            .where(
                ReservationWaitlist.id == entry_id,
                ReservationWaitlist.user_id == self.principal.user_id,
            )
            .with_for_update()
        )
        if entry is None or entry.status not in {"WAITING", "OFFERED", "NOTIFIED"}:
            raise ApiError("WAITLIST_NOT_FOUND", "候补申请不存在或已处理", 404)
        offer = await self.session.scalar(
            select(ReservationWaitlistOffer)
            .where(ReservationWaitlistOffer.waitlist_id == entry_id)
            .with_for_update()
        )
        entry.status = "CANCELLED"
        if offer is not None:
            await self.session.delete(offer)
            self._enqueue_waitlist_promotions(
                entry.device_id,
                [entry.reservation_date],
                entry.college_id,
                source_id=entry.id,
            )
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=self._college_id(),
            action="WAITLIST_CANCEL",
            target_type="WAITLIST",
            target_id=entry_id,
        )
        await self.session.commit()

    async def confirm_waitlist_offer(self, entry_id: int) -> WaitlistConfirmationData:
        if not self.principal.has_permission("reservation:create"):
            raise ApiError("FORBIDDEN", "当前账号没有确认候补预约的权限", 403)
        entry = await self.session.scalar(
            select(ReservationWaitlist)
            .where(
                ReservationWaitlist.id == entry_id,
                ReservationWaitlist.user_id == self.principal.user_id,
            )
            .with_for_update()
        )
        offer = await self.session.scalar(
            select(ReservationWaitlistOffer)
            .where(ReservationWaitlistOffer.waitlist_id == entry_id)
            .with_for_update()
        )
        if entry is None or offer is None or entry.status != "OFFERED":
            raise ApiError("WAITLIST_OFFER_NOT_FOUND", "候补预约保留已失效", 409)
        now = utcnow_naive()
        if offer.expires_at <= now or entry.reservation_date < date.today():
            entry.status = "EXPIRED" if offer.expires_at <= now else "SKIPPED"
            await self.session.delete(offer)
            self._enqueue_waitlist_promotions(
                entry.device_id,
                [entry.reservation_date],
                entry.college_id,
                source_id=entry.id,
            )
            await self.session.commit()
            raise ApiError("WAITLIST_OFFER_EXPIRED", "候补保留已过期，系统将递补下一位", 409)
        await self.session.delete(offer)
        entry.status = "CONFIRMED"
        await self.session.flush()
        plan = ReservationPlanRequest(
            device_id=entry.device_id,
            start_date=entry.reservation_date,
            end_date=entry.reservation_date,
            purpose=entry.purpose,
            purpose_category=entry.purpose_category,
            project_reference=entry.project_reference,
        )
        try:
            created = await self.create(plan, idempotency_key=f"waitlist-confirm:{entry.id}")
        except Exception:
            await self.session.rollback()
            raise
        if not created.created:
            raise ApiError("WAITLIST_CONFIRM_FAILED", "未能创建预约，请重试", 409)
        return WaitlistConfirmationData(waitlist_id=entry.id, reservation=created.created[0])

    async def create(
        self,
        plan: ReservationPlanRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ReservationCreateData:
        if not self.principal.has_permission("reservation:create"):
            raise ApiError("FORBIDDEN", "当前账号没有创建预约的权限", 403)
        if idempotency_key:
            if len(idempotency_key) > 128:
                raise ApiError("IDEMPOTENCY_KEY_INVALID", "幂等键长度不能超过 128", 422)
            key_hash = request_hash(plan)
            existing = await self.session.scalar(
                select(IdempotencyKey).where(
                    IdempotencyKey.user_id == self.principal.user_id,
                    IdempotencyKey.key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_hash != key_hash:
                    raise ApiError("IDEMPOTENCY_REUSED", "幂等键已用于另一份请求", 409)
                if existing.response_body:
                    return ReservationCreateData.model_validate(existing.response_body)
                raise ApiError("REQUEST_IN_PROGRESS", "相同请求正在处理中，请稍后重试", 409)

        if not self.principal.is_system_admin:
            user = await self.session.scalar(select(User).where(User.id == self.principal.user_id))
            now = utcnow_naive()
            if user is None or user.status != 1:
                raise ApiError("USER_NOT_FOUND", "用户不存在或已禁用", 401)
            if user.booking_blocked_until and user.booking_blocked_until > now:
                raise ApiError(
                    "BOOKING_RESTRICTED",
                    "当前信用状态暂时不能发起预约",
                    403,
                    data={"blocked_until": user.booking_blocked_until},
                )

        # Serialize policy/blackout checks against a maintenance-plan write for
        # the same device. The DB unique constraint on reservation day remains
        # the final conflict guard.
        device = await self._load_device(plan.device_id)
        device = await self.session.scalar(
            select(Device)
            .options(
                selectinload(Device.lab),
                selectinload(Device.college),
                selectinload(Device.category),
            )
            .where(Device.id == device.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if device is None:
            raise ApiError("DEVICE_NOT_FOUND", "设备不存在或不属于当前学院", 404)

        preflight = await self.preflight(plan)
        continuous_request = plan.start_date is not None or plan.windows is not None
        if preflight.conflicts and (
            plan.commit_mode == "all_or_nothing" or continuous_request
        ):
            raise ApiError(
                "RESERVATION_CONFLICT",
                "所选日期存在冲突，请查看冲突日期后重新提交",
                409,
                data=preflight.model_dump(mode="json"),
            )
        if preflight.safety_required and not preflight.safety_acknowledged:
            raise ApiError(
                "SAFETY_ACK_REQUIRED",
                "预约前请先阅读并确认最新版 SOP 和安全须知",
                409,
                data={"device_id": plan.device_id, "version": preflight.safety_document_version},
            )
        if preflight.qualification_required and not preflight.qualification_approved:
            raise ApiError(
                "QUALIFICATION_REQUIRED",
                "当前设备需要通过使用资质审核后才能预约",
                403,
                data={"device_id": plan.device_id},
            )
        selected = preflight.available_dates
        if not selected:
            raise ApiError(
                "NO_AVAILABLE_DATE",
                "所选日期均不可预约",
                409,
                data=preflight.model_dump(mode="json"),
            )

        explicit_batch = plan.dates is not None or plan.windows is not None
        selected_set = set(selected)
        segments = [
            [current for current in requested if current in selected_set]
            for requested in plan.reservation_segments()
        ]
        segments = [segment for segment in segments if segment]
        batch_id = uuid4().hex if explicit_batch or len(segments) > 1 else None
        created: list[ReservationData] = []
        status = "PENDING" if preflight.effective_policy.approval_required else "APPROVED"
        try:
            for segment in segments:
                reservation_now = utcnow_naive()
                reservation = Reservation(
                    college_id=device.college_id,
                    user_id=self.principal.user_id,
                    device_id=device.id,
                    purpose=plan.purpose.strip(),
                    purpose_category=plan.purpose_category,
                    project_reference=(
                        plan.project_reference.strip() if plan.project_reference else None
                    ),
                    start_date=segment[0],
                    end_date=segment[-1],
                    # Legacy MySQL installations still require these time
                    # columns to be non-null.  Natural-day reservations use
                    # the full-day boundaries so old readers remain
                    # compatible while the v2 conflict unit stays date-based.
                    start_time=datetime.combine(segment[0], time.min),
                    end_time=datetime.combine(segment[-1], time.max),
                    slot_count=len(segment),
                    status=status,
                    batch_id=batch_id,
                    handover_status="PENDING",
                    safety_acknowledged_at=(utcnow_naive() if preflight.safety_required else None),
                    safety_document_version=preflight.safety_document_version,
                    # MySQL does not reliably hydrate server defaults before
                    # the first flush with an async driver.  Set timestamps
                    # explicitly so response serialization never triggers an
                    # implicit lazy load (MissingGreenlet).
                    created_at=reservation_now,
                    updated_at=reservation_now,
                )
                reservation.device = device
                reservation.days = [
                    ReservationItem(device_id=device.id, reservation_date=current)
                    for current in segment
                ]
                self.session.add(reservation)
                await self.session.flush()
                if status == "APPROVED":
                    await self._enqueue_maintenance_impact_notifications(reservation)
                await self._ensure_handover_record(
                    reservation,
                    status="PENDING",
                    reservation_is_new=True,
                    now=reservation_now,
                )
                created.append(_reservation_data(reservation))
                self.session.add(
                    OutboxTask(
                        task_key=f"notification:reservation:{reservation.id}:created",
                        task_type="NOTIFICATION",
                        aggregate_key=f"reservation:{reservation.id}",
                        college_id=device.college_id,
                        payload={
                            "user_id": self.principal.user_id,
                            "college_id": device.college_id,
                            "type": "RESERVATION_CREATED",
                            "title": "预约申请已提交",
                            "content": (
                                "预约已提交，等待负责人审批。"
                                if status == "PENDING"
                                else "预约已确认，请在预约首日到场办理负责人设备交接。"
                            ),
                            "related_id": reservation.id,
                            "related_type": "RESERVATION",
                        },
                        execute_at=utcnow_naive(),
                    )
                )
                append_audit(
                    self.session,
                    user_id=self.principal.user_id,
                    college_id=device.college_id,
                    action="RESERVATION_CREATE",
                    target_type="RESERVATION",
                    target_id=reservation.id,
                    detail={"dates": [item.isoformat() for item in segment]},
                )
                if status == "APPROVED":
                    self.session.add(
                        OutboxTask(
                            task_key=f"timeout:reservation:{reservation.id}:no-show",
                            task_type="RESERVATION_NO_SHOW",
                            aggregate_key=f"reservation:{reservation.id}",
                            college_id=device.college_id,
                            payload={
                                "reservation_id": reservation.id,
                                "user_id": self.principal.user_id,
                                "college_id": device.college_id,
                            },
                            execute_at=_date_at_end(segment[0]),
                        )
                    )
                    self._enqueue_reservation_reminder(reservation, segment[0])

            response = ReservationCreateData(
                created=created,
                skipped_conflicts=(
                    preflight.conflicts if plan.commit_mode == "available_only" else []
                ),
                batch_id=batch_id,
            )
            if idempotency_key:
                self.session.add(
                    IdempotencyKey(
                        user_id=self.principal.user_id,
                        key=idempotency_key,
                        request_hash=request_hash(plan),
                        response_code="OK",
                        response_body=response.model_dump(mode="json"),
                        created_at=utcnow_naive(),
                    )
                )
            await self.session.commit()
            return response
        except IntegrityError as exc:
            await self.session.rollback()
            if idempotency_key:
                committed = await self.session.scalar(
                    select(IdempotencyKey).where(
                        IdempotencyKey.user_id == self.principal.user_id,
                        IdempotencyKey.key == idempotency_key,
                    )
                )
                if committed is not None and committed.request_hash == request_hash(plan):
                    if committed.response_body:
                        return ReservationCreateData.model_validate(committed.response_body)
                    raise ApiError(
                        "REQUEST_IN_PROGRESS",
                        "相同请求正在处理中，请稍后重试",
                        409,
                    ) from exc
            fresh = await self.preflight(plan)
            raise ApiError(
                "RESERVATION_CONFLICT",
                "提交过程中该日期已被其他用户占用，请重新选择可用日期",
                409,
                data=fresh.model_dump(mode="json"),
            ) from exc

    async def list_mine(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        handover_status: str | None = None,
    ) -> ReservationPage:
        if not self.principal.has_permission("reservation:read:own"):
            raise ApiError("FORBIDDEN", "当前账号没有查看个人预约的权限", 403)
        page_offset(page, page_size)
        base_conditions = [Reservation.user_id == self.principal.user_id]
        scope = self._college_id()
        if scope is not None:
            base_conditions.append(Reservation.college_id == scope)
        if status:
            base_conditions.append(Reservation.status == status)
        if handover_status:
            base_conditions.append(Reservation.handover_status == handover_status)
        total = int(
            await self.session.scalar(select(func.count(Reservation.id)).where(*base_conditions))
            or 0
        )
        page_ids = delayed_page_ids(
            select(Reservation.id).where(*base_conditions),
            Reservation.id,
            page=page,
            page_size=page_size,
        )
        stmt = (
            select(Reservation)
            .join(page_ids, page_ids.c.id == Reservation.id)
            .options(
                selectinload(Reservation.device),
                selectinload(Reservation.days),
                selectinload(Reservation.inspections),
                selectinload(Reservation.handover),
                selectinload(Reservation.fault_repair),
            )
            .order_by(Reservation.id.desc())
        )
        reservations = list((await self.session.scalars(stmt)).all())
        pages, truncated = page_metadata(total, page_size)
        return ReservationPage(
            items=[_reservation_data(item) for item in reservations],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            truncated=truncated,
        )

    async def get_reservation(self, reservation_id: int) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
        if not await self._can_view(reservation):
            raise ApiError("RESERVATION_NOT_FOUND", "预约不存在或无权访问", 404)
        return _reservation_data(reservation)

    async def _load_reservation(self, reservation_id: int) -> Reservation:
        reservation = await self.session.scalar(
            select(Reservation)
            .options(
                selectinload(Reservation.device).selectinload(Device.lab),
                selectinload(Reservation.device).selectinload(Device.college),
                selectinload(Reservation.days),
                selectinload(Reservation.user),
                selectinload(Reservation.inspections),
                selectinload(Reservation.handover),
                selectinload(Reservation.fault_repair),
            )
            .where(Reservation.id == reservation_id)
        )
        if reservation is None:
            raise ApiError("RESERVATION_NOT_FOUND", "预约不存在", 404)
        return reservation

    async def _can_view(self, reservation: Reservation) -> bool:
        if reservation.user_id == self.principal.user_id:
            return self.principal.has_permission("reservation:read:own") and (
                self._college_id() is None or reservation.college_id == self._college_id()
            )
        if self.principal.is_system_admin:
            return self._college_id() is None or reservation.college_id == self._college_id()
        return self.principal.has_permission(
            "reservation:read:scope"
        ) and await self._can_manage_device(reservation.device)

    async def _can_manage_device(self, device: Device) -> bool:
        if self.principal.is_system_admin:
            return True
        scope = self._college_id()
        if not self.principal.is_lab_admin or scope is None or device.college_id != scope:
            return False
        if device.lab_id is None:
            college_manager = await self.session.scalar(
                select(College.manager_id).where(College.id == device.college_id)
            )
            return college_manager == self.principal.user_id
        manager_id = await self.session.scalar(
            select(Lab.manager_id).where(Lab.id == device.lab_id)
        )
        if manager_id == self.principal.user_id:
            return True
        college_manager = await self.session.scalar(
            select(College.manager_id).where(College.id == device.college_id)
        )
        return college_manager == self.principal.user_id

    async def cancel(self, reservation_id: int) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
        if not self.principal.has_permission("reservation:cancel"):
            raise ApiError("FORBIDDEN", "当前账号没有取消预约的权限", 403)
        if reservation.user_id != self.principal.user_id and not self.principal.is_system_admin:
            raise ApiError("FORBIDDEN", "只能取消自己的预约", 403)
        if not await self._can_view(reservation):
            raise ApiError("RESERVATION_NOT_FOUND", "预约不存在或无权操作", 404)
        if reservation.status not in ACTIVE_RESERVATION_STATUSES:
            raise ApiError("INVALID_RESERVATION_STATE", "当前状态不能取消", 409)
        if reservation.status == "IN_USE":
            raise ApiError("INVALID_RESERVATION_STATE", "设备使用中，请先完成归还验收", 409)
        if date.today() >= reservation.start_date:
            raise ApiError("CANCEL_WINDOW_CLOSED", "预约开始日当天及之后不能取消", 409)
        result = await self.session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
            .values(status="CANCELLED")
        )
        if result.rowcount != 1:
            raise ApiError("RESERVATION_STATE_CHANGED", "预约状态已被其他操作修改", 409)
        await self._set_handover_status(reservation, "CANCELLED")
        released_dates = [item.reservation_date for item in reservation.days]
        await self.session.execute(
            delete(ReservationItem).where(ReservationItem.reservation_id == reservation_id)
        )
        self._enqueue_waitlist_promotions(
            reservation.device_id,
            released_dates,
            reservation.college_id,
            source_id=reservation.id,
        )
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=reservation.college_id,
            action="RESERVATION_CANCEL",
            target_type="RESERVATION",
            target_id=reservation.id,
        )
        await self.session.commit()
        reservation.status = "CANCELLED"
        return _reservation_data(reservation)

    async def cancel_handover_exception(
        self,
        reservation_id: int,
        reason: str,
    ) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
        if not self.principal.has_permission("reservation:handover"):
            raise ApiError("FORBIDDEN", "当前账号没有处理交接异常的权限", 403)
        if not await self._can_manage_device(reservation.device):
            raise ApiError("FORBIDDEN", "只能处理自己负责范围内的预约", 403)
        if reservation.status != "APPROVED" or reservation.handover_status != "EXCEPTION":
            raise ApiError("INVALID_RESERVATION_STATE", "只有交接异常且尚未开始的预约可以取消", 409)
        cleaned_reason = reason.strip()
        if len(cleaned_reason) < 2:
            raise ApiError("CANCEL_REASON_REQUIRED", "请填写取消原因", 422)
        result = await self.session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status == "APPROVED",
                Reservation.handover_status == "EXCEPTION",
            )
            .values(status="CANCELLED", handover_status="CANCELLED", reject_reason=cleaned_reason)
        )
        if result.rowcount != 1:
            raise ApiError("RESERVATION_STATE_CHANGED", "预约状态已被其他操作修改", 409)
        await self._set_handover_status(reservation, "CANCELLED")
        released_dates = [item.reservation_date for item in reservation.days]
        await self.session.execute(
            delete(ReservationItem).where(ReservationItem.reservation_id == reservation.id)
        )
        self._enqueue_waitlist_promotions(
            reservation.device_id,
            released_dates,
            reservation.college_id,
            source_id=reservation.id,
        )
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:handover-cancelled",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "RESERVATION_UPDATE",
                    "title": "交接异常，预约已取消",
                    "content": (
                        f"设备交接异常已转维修，负责人已取消预约。原因：{cleaned_reason}。"
                        "你可以重新选择本学院其他可用设备预约。"
                    ),
                    "related_id": reservation.id,
                    "related_type": "RESERVATION",
                },
                execute_at=utcnow_naive(),
            )
        )
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=reservation.college_id,
            action="RESERVATION_CANCEL_HANDOVER_EXCEPTION",
            target_type="RESERVATION",
            target_id=reservation.id,
            detail={"reason": cleaned_reason},
        )
        await self.session.commit()
        reservation.status = "CANCELLED"
        reservation.handover_status = "CANCELLED"
        return _reservation_data(reservation)

    async def approve(
        self,
        reservation_id: int,
        approve: bool,
        reason: str | None = None,
    ) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
        if not self.principal.has_permission("reservation:approve"):
            raise ApiError("FORBIDDEN", "当前账号没有审批预约的权限", 403)
        if not await self._can_manage_device(reservation.device):
            raise ApiError("FORBIDDEN", "只能审批自己负责实验室或学院的设备", 403)
        if reservation.status != "PENDING":
            raise ApiError("INVALID_RESERVATION_STATE", "只有待审批预约可以审批", 409)
        if approve and reservation.device.status in {
            "MAINTENANCE",
            "DISABLED",
            "OFFLINE",
            "RETIRED",
        }:
            raise ApiError("DEVICE_UNAVAILABLE", "设备当前不可用，不能通过预约", 409)
        if approve:
            reserved_dates = [
                reservation.start_date + timedelta(days=offset)
                for offset in range((reservation.end_date - reservation.start_date).days + 1)
            ]
            blocked_dates = await self._blocked_dates(reservation.device, reserved_dates)
            if blocked_dates:
                first_date, reason = min(blocked_dates.items())
                raise ApiError(
                    "DEVICE_MAINTENANCE_RESTRICTION",
                    f"预约日期 {first_date} 不可用：{reason}",
                    409,
                )
        next_status = "APPROVED" if approve else "REJECTED"
        values: dict[str, object] = {
            "status": next_status,
            "approver_id": self.principal.user_id,
            "approved_at": utcnow_naive() if approve else None,
            "reject_reason": None if approve else (reason or "负责人拒绝了该预约"),
        }
        result = await self.session.execute(
            update(Reservation)
            .where(Reservation.id == reservation_id, Reservation.status == "PENDING")
            .values(**values)
        )
        if result.rowcount != 1:
            raise ApiError("RESERVATION_STATE_CHANGED", "预约已被其他操作处理", 409)
        if approve:
            await self._ensure_handover_record(reservation, status="PENDING")
            await self._enqueue_maintenance_impact_notifications(reservation)
        else:
            await self._set_handover_status(reservation, "CANCELLED")
        self._enqueue_approval_notification(
            reservation,
            approved=approve,
            reason=reason,
        )
        if approve:
            self.session.add(
                OutboxTask(
                    task_key=f"timeout:reservation:{reservation_id}:no-show",
                    task_type="RESERVATION_NO_SHOW",
                    aggregate_key=f"reservation:{reservation_id}",
                    college_id=reservation.college_id,
                    payload={
                        "reservation_id": reservation_id,
                        "user_id": reservation.user_id,
                        "college_id": reservation.college_id,
                    },
                    execute_at=_date_at_end(reservation.start_date),
                )
            )
            self._enqueue_reservation_reminder(reservation, reservation.start_date)
        else:
            released_dates = [item.reservation_date for item in reservation.days]
            await self.session.execute(
                delete(ReservationItem).where(ReservationItem.reservation_id == reservation_id)
            )
            self._enqueue_waitlist_promotions(
                reservation.device_id,
                released_dates,
                reservation.college_id,
                source_id=reservation.id,
            )
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=reservation.college_id,
            action="RESERVATION_APPROVE" if approve else "RESERVATION_REJECT",
            target_type="RESERVATION",
            target_id=reservation.id,
            detail={"reason": reason},
        )
        await self.session.commit()
        reservation.status = next_status
        return _reservation_data(reservation)

    async def approve_many(self, reservation_ids: list[int]) -> int:
        """Approve a batch in one transaction after validating every row and scope."""
        unique_ids = list(dict.fromkeys(reservation_ids))
        if not unique_ids:
            raise ApiError("APPROVAL_EMPTY", "至少选择一条待审批预约", 422)
        if not self.principal.has_permission("reservation:approve"):
            raise ApiError("FORBIDDEN", "当前角色无审批权限", 403)
        reservations = list(
            (
                await self.session.scalars(
                    select(Reservation)
                    .options(
                        selectinload(Reservation.device).selectinload(Device.lab),
                        selectinload(Reservation.device).selectinload(Device.college),
                    )
                    .where(Reservation.id.in_(unique_ids))
                    .with_for_update()
                )
            ).all()
        )
        if len(reservations) != len(unique_ids):
            raise ApiError("RESERVATION_NOT_FOUND", "部分预约不存在或已被删除", 404)
        dates_by_reservation: dict[int, list[date]] = {}
        dates_by_device: dict[int, set[date]] = {}
        devices_by_id = {reservation.device.id: reservation.device for reservation in reservations}
        for reservation in reservations:
            if reservation.status != "PENDING":
                raise ApiError("INVALID_RESERVATION_STATE", "批量审批中存在非待审批预约", 409)
            if not await self._can_manage_device(reservation.device):
                raise ApiError("FORBIDDEN", "批量审批包含不在管理范围内的设备", 403)
            if reservation.device.status in {"MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED"}:
                raise ApiError("DEVICE_UNAVAILABLE", "批量审批中包含不可用设备", 409)
            reserved_dates = [
                reservation.start_date + timedelta(days=offset)
                for offset in range((reservation.end_date - reservation.start_date).days + 1)
            ]
            dates_by_reservation[reservation.id] = reserved_dates
            dates_by_device.setdefault(reservation.device.id, set()).update(reserved_dates)

        blocked_by_device = await self._blocked_dates_for_devices(
            devices_by_id,
            dates_by_device,
        )
        for reservation in reservations:
            blocked = blocked_by_device.get(reservation.device.id, {})
            if any(day in blocked for day in dates_by_reservation[reservation.id]):
                raise ApiError(
                    "DEVICE_MAINTENANCE_RESTRICTION",
                    f"预约 #{reservation.id} 的日期与维护/不可预约规则冲突，不能通过",
                    409,
                )
        now = utcnow_naive()
        for reservation in reservations:
            reservation.status = "APPROVED"
            reservation.approver_id = self.principal.user_id
            reservation.approved_at = now
            await self._ensure_handover_record(
                reservation,
                status="PENDING",
                now=now,
            )
            self._enqueue_approval_notification(reservation, approved=True)
            self.session.add(
                OutboxTask(
                    task_key=f"timeout:reservation:{reservation.id}:no-show",
                    task_type="RESERVATION_NO_SHOW",
                    aggregate_key=f"reservation:{reservation.id}",
                    college_id=reservation.college_id,
                    payload={
                        "reservation_id": reservation.id,
                        "user_id": reservation.user_id,
                        "college_id": reservation.college_id,
                    },
                    execute_at=_date_at_end(reservation.start_date),
                )
            )
            self._enqueue_reservation_reminder(reservation, reservation.start_date)
            append_audit(
                self.session,
                user_id=self.principal.user_id,
                college_id=reservation.college_id,
                action="RESERVATION_APPROVE",
                target_type="RESERVATION",
                target_id=reservation.id,
            )
        await self._enqueue_maintenance_impact_notifications_many(reservations)
        await self.session.commit()
        return len(reservations)

    async def violate(self, reservation_id: int, reason: str) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
        if not self.principal.has_permission("reservation:approve"):
            raise ApiError("FORBIDDEN", "当前账号没有处理预约违规的权限", 403)
        if not await self._can_manage_device(reservation.device):
            raise ApiError("FORBIDDEN", "只能处理自己负责范围内的预约", 403)
        if reservation.status not in {"APPROVED", "IN_USE"}:
            raise ApiError("INVALID_RESERVATION_STATE", "当前状态不能标记违规", 409)
        result = await self.session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status.in_(("APPROVED", "IN_USE")),
            )
            .values(status="VIOLATED", reject_reason=reason.strip())
        )
        if result.rowcount != 1:
            raise ApiError("RESERVATION_STATE_CHANGED", "预约状态已被其他操作修改", 409)
        await self._set_handover_status(reservation, "CANCELLED")
        released_dates = [item.reservation_date for item in reservation.days]
        await self.session.execute(
            delete(ReservationItem).where(ReservationItem.reservation_id == reservation_id)
        )
        user = await self.session.scalar(select(User).where(User.id == reservation.user_id))
        if user is not None:
            user.credit_score = max(0, user.credit_score - 20)
            if user.credit_score < self.credit_block_threshold:
                user.booking_blocked_until = utcnow_naive() + timedelta(days=self.credit_block_days)
            self.session.add(
                CreditEvent(
                    user_id=user.id,
                    college_id=reservation.college_id,
                    reservation_id=reservation.id,
                    event_type="VIOLATION",
                    points=-20,
                    reason=reason.strip(),
                    operator_id=self.principal.user_id,
                    created_at=utcnow_naive(),
                )
            )
        self._enqueue_waitlist_promotions(
            reservation.device_id,
            released_dates,
            reservation.college_id,
            source_id=reservation.id,
        )
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:violated",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "RESERVATION_VIOLATED",
                    "title": "预约已标记违规",
                    "content": f"预约已被负责人标记为违规。原因：{reason.strip()}",
                    "related_id": reservation.id,
                    "related_type": "RESERVATION",
                },
                execute_at=utcnow_naive(),
            )
        )
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=reservation.college_id,
            action="RESERVATION_VIOLATE",
            target_type="RESERVATION",
            target_id=reservation.id,
            detail={"reason": reason.strip()},
        )
        await self.session.commit()
        reservation.status = "VIOLATED"
        return _reservation_data(reservation)

    def _enqueue_approval_notification(
        self,
        reservation: Reservation,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> None:
        device_name = (
            reservation.device.name if reservation.device else f"设备 #{reservation.device_id}"
        )
        if approved:
            title = "预约申请已通过"
            content = f"设备“{device_name}”的预约已通过，请在预约首日到场办理负责人设备交接。"
            suffix = "approved"
        else:
            title = "预约申请已驳回"
            content = f"设备“{device_name}”的预约已驳回。原因：{reason or '负责人拒绝了该预约'}"
            suffix = "rejected"
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:{suffix}",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "APPROVAL",
                    "title": title,
                    "content": content,
                    "related_id": reservation.id,
                    "related_type": "RESERVATION",
                },
                execute_at=utcnow_naive(),
            )
        )

    async def _enqueue_maintenance_impact_notifications(
        self,
        reservation: Reservation,
    ) -> None:
        await self._enqueue_maintenance_impact_notifications_many([reservation])

    async def _enqueue_maintenance_impact_notifications_many(
        self,
        reservations: list[Reservation],
    ) -> None:
        """Notify newly approved users if a due-maintenance notice already ran.

        The plan row lock serializes this check with the due-date worker: either
        that worker sees this reservation, or this transaction observes its
        sent marker and enqueues the same deterministic impact task. Batch
        approvals resolve and lock plans in one query, independent of batch size.
        """
        if not reservations:
            return
        device_ids = {reservation.device_id for reservation in reservations}
        plans = list(
            (
                await self.session.scalars(
                    select(DeviceMaintenancePlan)
                    .where(
                        DeviceMaintenancePlan.device_id.in_(device_ids),
                        DeviceMaintenancePlan.active.is_(True),
                        DeviceMaintenancePlan.plan_type.in_(
                            ("CALIBRATION", "SAFETY_CHECK")
                        ),
                        DeviceMaintenancePlan.due_date
                        < max(reservation.end_date for reservation in reservations),
                    )
                    .order_by(DeviceMaintenancePlan.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        plans_by_device: dict[int, list[DeviceMaintenancePlan]] = {}
        for plan in plans:
            if plan.due_notice_sent_at is not None:
                plans_by_device.setdefault(plan.device_id, []).append(plan)
        task_keys = [
            f"maintenance:impact:{plan.id}:{reservation.id}:{plan.due_date.isoformat()}"
            for reservation in reservations
            for plan in plans_by_device.get(reservation.device_id, [])
            if reservation.end_date > plan.due_date
        ]
        existing_keys = (
            set(
                (
                    await self.session.scalars(
                        select(OutboxTask.task_key).where(OutboxTask.task_key.in_(task_keys))
                    )
                ).all()
            )
            if task_keys
            else set()
        )
        for reservation in reservations:
            for plan in plans_by_device.get(reservation.device_id, []):
                if reservation.end_date <= plan.due_date:
                    continue
                due_date = plan.due_date.isoformat()
                task_key = f"maintenance:impact:{plan.id}:{reservation.id}:{due_date}"
                if task_key in existing_keys:
                    continue
                device_name = (
                    reservation.device.name
                    if reservation.device is not None
                    else f"设备 #{reservation.device_id}"
                )
                self.session.add(
                    OutboxTask(
                        task_key=task_key,
                        task_type="NOTIFICATION",
                        aggregate_key=f"maintenance:{plan.id}:due:{due_date}",
                        college_id=reservation.college_id,
                        payload={
                            "user_id": reservation.user_id,
                            "college_id": reservation.college_id,
                            "type": "MAINTENANCE_DUE",
                            "title": "预约受维护到期影响",
                            "content": (
                                f"设备“{device_name}”的{plan.title}已到期。"
                                "该预约不会自动取消；若维护逾期，交接/使用将被阻止，"
                                "请联系负责人处理。"
                            ),
                            "related_id": plan.id,
                            "related_type": "MAINTENANCE_PLAN",
                        },
                        execute_at=utcnow_naive(),
                    )
                )

    def _enqueue_reservation_reminder(self, reservation: Reservation, start_date: date) -> None:
        reminder_at = datetime.combine(start_date - timedelta(days=1), time.min)
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:reminder",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "RESERVATION_REMINDER",
                    "title": "预约即将开始",
                    "content": (
                        f"设备“{reservation.device.name}”将在 {start_date.isoformat()} 开始预约，"
                        "请在预约首日到场办理负责人设备交接。"
                    ),
                    "related_id": reservation.id,
                    "related_type": "RESERVATION",
                },
                execute_at=reminder_at,
            )
        )

    def _enqueue_waitlist_promotions(
        self,
        device_id: int,
        dates: list[date],
        college_id: int | None,
        source_id: int | None = None,
    ) -> None:
        for reserved_date in sorted(set(dates)):
            iso_date = reserved_date.isoformat()
            self.session.add(
                OutboxTask(
                    task_key=(f"waitlist:promote:{device_id}:{iso_date}:{source_id or 'manual'}"),
                    task_type="WAITLIST_PROMOTE",
                    aggregate_key=f"waitlist:{device_id}:{iso_date}",
                    college_id=college_id,
                    payload={
                        "device_id": device_id,
                        "reservation_date": iso_date,
                    },
                    execute_at=utcnow_naive(),
                )
            )

    async def check_in(self, reservation_id: int) -> ReservationData:
        if not self.principal.has_permission("reservation:check-in"):
            raise ApiError("FORBIDDEN", "当前账号没有预约签到的权限", 403)
        reservation = await self._load_reservation(reservation_id)
        if reservation.user_id != self.principal.user_id:
            raise ApiError("FORBIDDEN", "只能操作自己的预约", 403)
        raise ApiError("HANDOVER_REQUIRED", "所有预约均由负责人完成交接后才能开始使用", 409)

    async def return_device(
        self,
        reservation_id: int,
        *,
        condition: str = "NORMAL",
        note: str | None = None,
        image_urls: list[str] | None = None,
    ) -> ReservationData:
        if not self.principal.has_permission("reservation:return"):
            raise ApiError("FORBIDDEN", "当前账号没有提交归还的权限", 403)
        reservation = await self._load_reservation(reservation_id)
        if reservation.user_id != self.principal.user_id:
            raise ApiError("FORBIDDEN", "只能操作自己的预约", 403)
        if reservation.status != "IN_USE":
            raise ApiError("INVALID_RESERVATION_STATE", "只有使用中的预约可以归还", 409)
        if reservation.handover_status == "RETURN_PENDING":
            raise ApiError("INVALID_RESERVATION_STATE", "设备已归还，正在等待负责人验收", 409)
        if date.today() != reservation.end_date:
            raise ApiError("RETURN_DAY_INVALID", "预约结束日才能归还", 409)
        if condition not in {"NORMAL", "DAMAGED", "MISSING"}:
            raise ApiError("INSPECTION_INVALID", "归还验收状态无效", 422)
        if reservation.device.status in {"DISABLED", "OFFLINE", "RETIRED"}:
            raise ApiError("DEVICE_UNAVAILABLE", "当前设备状态不允许履约操作", 409)
        image_urls = await self._validate_evidence_images(image_urls, reservation.device)

        previous_handover_status = reservation.handover_status
        if previous_handover_status not in {"HANDED_OVER", "LEGACY_IN_USE", "NOT_REQUIRED"}:
            raise ApiError("INVALID_RESERVATION_STATE", "当前预约尚未完成设备交接", 409)
        now = utcnow_naive()
        result = await self.session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.user_id == self.principal.user_id,
                Reservation.status == "IN_USE",
                Reservation.handover_status == previous_handover_status,
            )
            .values(handover_status="RETURN_PENDING")
        )
        if result.rowcount != 1:
            raise ApiError("RESERVATION_STATE_CHANGED", "预约状态已被其他操作修改", 409)

        handover = await self._ensure_handover_record(
            reservation,
            status="RETURN_PENDING",
            now=now,
        )
        handover.returned_by = self.principal.user_id
        handover.returned_at = now
        handover.return_condition = condition
        handover.return_note = note.strip() if note else None
        handover.return_image_urls = image_urls
        handover.updated_at = now
        reservation.handover_status = "RETURN_PENDING"
        inspection = ReservationInspection(
            reservation_id=reservation.id,
            device_id=reservation.device_id,
            user_id=self.principal.user_id,
            condition=condition,
            note=note.strip() if note else None,
            image_urls=image_urls,
            created_at=now,
        )
        reservation.inspections.append(inspection)
        self.session.add(inspection)
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:return_pending",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "RESERVATION_UPDATE",
                    "title": "设备已归还，等待验收",
                    "content": f"设备“{reservation.device.name}”已归还，请等待负责人完成验收。",
                    "related_id": reservation.id,
                    "related_type": "RESERVATION",
                },
                execute_at=now,
            )
        )
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=reservation.college_id,
            action="RESERVATION_RETURN_REQUEST",
            target_type="RESERVATION",
            target_id=reservation.id,
            detail={"condition": condition, "note": note},
        )
        await self.session.commit()
        reservation.status = "IN_USE"
        reservation.handover_status = "RETURN_PENDING"
        reservation.handover = handover
        return _reservation_data(reservation)

    async def handover(
        self,
        reservation_id: int,
        *,
        condition: str = "NORMAL",
        note: str | None = None,
        image_urls: list[str] | None = None,
        checklist: list[object] | None = None,
    ) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
        if not self.principal.has_permission("reservation:handover"):
            raise ApiError("FORBIDDEN", "当前账号没有办理设备交接的权限", 403)
        if not await self._can_manage_device(reservation.device):
            raise ApiError("FORBIDDEN", "只能交接自己负责范围内的设备", 403)
        if reservation.status != "APPROVED":
            raise ApiError("INVALID_RESERVATION_STATE", "只有已审批预约可以办理领用交接", 409)
        if date.today() != reservation.start_date:
            raise ApiError("HANDOVER_DAY_INVALID", "预约首日才能办理设备交接", 409)
        locked_device = await self.session.scalar(
            select(Device)
            .where(Device.id == reservation.device_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_device is None or locked_device.status != "IDLE":
            raise ApiError("DEVICE_UNAVAILABLE", "设备当前不可交接，请先确认设备状态", 409)
        reservation_dates = [
            reservation.start_date + timedelta(days=offset)
            for offset in range((reservation.end_date - reservation.start_date).days + 1)
        ]
        maintenance_blocks = await self._blocked_dates(locked_device, reservation_dates)
        if maintenance_blocks:
            first_date, reason = min(maintenance_blocks.items())
            raise ApiError(
                "DEVICE_MAINTENANCE_RESTRICTION",
                f"设备在预约日期 {first_date} 不可交接或使用：{reason}",
                409,
            )
        open_repairs = int(
            await self.session.scalar(
                select(func.count(RepairReport.id)).where(
                    RepairReport.device_id == reservation.device_id,
                    RepairReport.status.in_(OPEN_REPAIR_STATUSES),
                )
            )
            or 0
        )
        if open_repairs:
            raise ApiError("DEVICE_REPAIR_OPEN", "设备存在未完成报修，不能办理交接", 409)
        if condition not in {"NORMAL", "DAMAGED", "MISSING"}:
            raise ApiError("HANDOVER_CONDITION_INVALID", "交接设备状态无效", 422)
        now = utcnow_naive()
        images = await self._validate_evidence_images(image_urls, reservation.device)
        accessory_snapshot = (
            reservation.handover.accessory_snapshot
            if reservation.handover is not None
            else reservation.device.accessory_checklist
        )
        checks = self._validated_checklist(accessory_snapshot, checklist)
        condition = self._effective_condition(condition, checks)
        next_handover_status = "EXCEPTION" if condition != "NORMAL" else "HANDED_OVER"
        result = await self.session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status == "APPROVED",
                Reservation.handover_status == "PENDING",
            )
            .values(
                status="APPROVED" if condition != "NORMAL" else "IN_USE",
                handover_status=next_handover_status,
                check_in_at=None if condition != "NORMAL" else now,
            )
        )
        if result.rowcount != 1:
            raise ApiError("RESERVATION_STATE_CHANGED", "预约状态已被其他操作修改", 409)

        handover = await self._ensure_handover_record(
            reservation,
            status=next_handover_status,
            now=now,
        )
        handover.handover_by = self.principal.user_id
        handover.handover_at = now
        handover.handover_condition = condition
        handover.handover_note = note.strip() if note else None
        handover.handover_checklist = checks
        handover.handover_image_urls = images
        handover.updated_at = now

        if condition != "NORMAL":
            repair = await self._create_fault_repair(
                reservation,
                phase="领用交接",
                condition=condition,
                note=note,
                image_urls=images,
                checklist=checks,
                now=now,
            )
            append_audit(
                self.session,
                user_id=self.principal.user_id,
                college_id=reservation.college_id,
                action="DEVICE_HANDOVER_EXCEPTION",
                target_type="RESERVATION",
                target_id=reservation.id,
                detail={"condition": condition, "repair_id": repair.id},
            )
            await self.session.commit()
            reservation.status = "APPROVED"
            reservation.handover_status = "EXCEPTION"
            return _reservation_data(reservation)

        handover.status = "HANDED_OVER"
        handover.updated_at = now
        if change_device_status(
            self.session,
            reservation.device,
            "IN_USE",
            operator_id=self.principal.user_id,
            reason="负责人完成预约设备交接",
        ):
            enqueue_catalog_cache_bump(self.session, reservation.college_id)
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=reservation.college_id,
            action="DEVICE_HANDOVER",
            target_type="RESERVATION",
            target_id=reservation.id,
            detail={"condition": condition, "note": note},
        )
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:handover",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "RESERVATION_UPDATE",
                    "title": "设备已完成交接",
                    "content": f"设备“{reservation.device.name}”已完成领用交接，可以开始使用。",
                    "related_id": reservation.id,
                    "related_type": "RESERVATION",
                },
                execute_at=now,
            )
        )
        await self.session.commit()
        reservation.status = "IN_USE"
        reservation.check_in_at = now
        reservation.handover_status = "HANDED_OVER"
        reservation.handover = handover
        return _reservation_data(reservation)

    async def accept_return(
        self,
        reservation_id: int,
        *,
        condition: str = "NORMAL",
        note: str | None = None,
        checklist: list[object] | None = None,
    ) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
        if not self.principal.has_permission("reservation:accept-return"):
            raise ApiError("FORBIDDEN", "当前账号没有验收设备归还的权限", 403)
        if not await self._can_manage_device(reservation.device):
            raise ApiError("FORBIDDEN", "只能验收自己负责范围内的设备", 403)
        if reservation.status != "IN_USE" or reservation.handover_status != "RETURN_PENDING":
            raise ApiError("INVALID_RESERVATION_STATE", "当前预约不在待验收状态", 409)
        if condition not in {"NORMAL", "DAMAGED", "MISSING"}:
            raise ApiError("INSPECTION_INVALID", "归还验收状态无效", 422)
        now = utcnow_naive()
        handover = await self.session.scalar(
            select(DeviceHandover).where(DeviceHandover.reservation_id == reservation.id)
        )
        if handover is None or not handover.return_image_urls:
            raise ApiError("RETURN_EVIDENCE_REQUIRED", "归还照片缺失，无法完成验收", 409)
        checks = self._validated_checklist(handover.accessory_snapshot, checklist)
        condition = self._effective_condition(condition, checks)
        open_repairs = int(
            await self.session.scalar(
                select(func.count(RepairReport.id)).where(
                    RepairReport.device_id == reservation.device_id,
                    RepairReport.status.in_(("PENDING", "PROCESSING", "RESOLVED")),
                )
            )
            or 0
        )
        target_status = "MAINTENANCE" if condition != "NORMAL" or open_repairs else "IDLE"
        inspection = (reservation.inspections or [None])[-1]
        if inspection is None:
            inspection = ReservationInspection(
                reservation_id=reservation.id,
                device_id=reservation.device_id,
                user_id=reservation.user_id,
                created_at=now,
            )
            self.session.add(inspection)
        inspection.condition = condition
        inspection.note = note.strip() if note else inspection.note
        inspection.checklist = checks
        handover.return_checklist = checks
        handover.return_condition = condition
        handover.return_note = note.strip() if note else handover.return_note
        handover.updated_at = now
        result = await self.session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status == "IN_USE",
                Reservation.handover_status == "RETURN_PENDING",
            )
            .values(status="COMPLETED", check_out_at=now, handover_status="RETURNED")
        )
        if result.rowcount != 1:
            raise ApiError("RESERVATION_STATE_CHANGED", "归还验收状态已被其他操作修改", 409)
        await self.session.execute(
            delete(ReservationItem).where(ReservationItem.reservation_id == reservation.id)
        )
        handover.status = "RETURNED"
        handover.returned_by = handover.returned_by or self.principal.user_id
        handover.returned_at = handover.returned_at or now
        handover.return_condition = condition
        handover.return_note = note.strip() if note else handover.return_note
        handover.updated_at = now
        repair = None
        if condition != "NORMAL":
            repair = await self._create_fault_repair(
                reservation,
                phase="归还验收",
                condition=condition,
                note=note,
                image_urls=list(handover.return_image_urls),
                checklist=checks,
                now=now,
            )
        else:
            if change_device_status(
                self.session,
                reservation.device,
                target_status,
                operator_id=self.principal.user_id,
                reason=note or "预约设备归还验收",
            ):
                enqueue_catalog_cache_bump(self.session, reservation.college_id)
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=reservation.college_id,
            action="DEVICE_RETURN_ACCEPT",
            target_type="RESERVATION",
            target_id=reservation.id,
            detail={"condition": condition, "note": note, "device_status": target_status},
        )
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:return-accepted",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "RESERVATION_UPDATE",
                    "title": "设备归还已验收",
                    "content": f"设备“{reservation.device.name}”归还验收已完成。",
                    "related_id": reservation.id,
                    "related_type": "RESERVATION",
                },
                execute_at=now,
            )
        )
        await self.session.commit()
        reservation.status = "COMPLETED"
        reservation.check_out_at = now
        reservation.handover_status = "RETURNED"
        reservation.handover = handover
        if repair is not None:
            reservation.fault_repair = repair
        return _reservation_data(reservation)

    async def pending_approvals(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> ReservationPage:
        scope = self._college_id()
        if not self.principal.has_permission("reservation:approve"):
            raise ApiError("FORBIDDEN", "当前角色无审批权限", 403)
        page_offset(page, page_size)
        conditions = [Reservation.status == "PENDING"]
        if scope is not None:
            conditions.extend(
                [
                    Reservation.college_id == scope,
                    or_(
                        Lab.manager_id == self.principal.user_id,
                        College.manager_id == self.principal.user_id,
                    ),
                ]
            )
        page_ids = delayed_page_ids(
            select(Reservation.id)
            .join(Device, Device.id == Reservation.device_id)
            .outerjoin(Lab, Lab.id == Device.lab_id)
            .join(College, College.id == Device.college_id)
            .where(*conditions),
            Reservation.id,
            page=page,
            page_size=page_size,
        )
        stmt = (
            select(Reservation)
            .join(page_ids, page_ids.c.id == Reservation.id)
            .options(
                selectinload(Reservation.device),
                selectinload(Reservation.days),
                selectinload(Reservation.user),
                selectinload(Reservation.handover),
            )
            .order_by(Reservation.id.desc())
        )
        reservations = list((await self.session.scalars(stmt)).all())
        total = int(
            await self.session.scalar(
                select(func.count(Reservation.id))
                .join(Device, Device.id == Reservation.device_id)
                .outerjoin(Lab, Lab.id == Device.lab_id)
                .join(College, College.id == Device.college_id)
                .where(
                    Reservation.status == "PENDING",
                    *([Reservation.college_id == scope] if scope is not None else []),
                    *(
                        [
                            or_(
                                Lab.manager_id == self.principal.user_id,
                                College.manager_id == self.principal.user_id,
                            )
                        ]
                        if scope is not None
                        else []
                    ),
                )
            )
            or 0
        )
        pages, truncated = page_metadata(total, page_size)
        return ReservationPage(
            items=[_reservation_data(item) for item in reservations],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            truncated=truncated,
        )

    async def pending_handovers(
        self,
        *,
        status: str = "PENDING",
        page: int = 1,
        page_size: int = 20,
    ) -> ReservationPage:
        """Return manager-scoped reservation handovers and return inspections."""

        if status not in {"PENDING", "RETURN_PENDING", "EXCEPTION"}:
            raise ApiError("HANDOVER_STATUS_INVALID", "交接状态无效", 422)
        if not (
            self.principal.has_permission("reservation:handover")
            or self.principal.has_permission("reservation:accept-return")
        ):
            raise ApiError("FORBIDDEN", "当前角色无设备交接权限", 403)
        page_offset(page, page_size)
        scope = self._college_id()
        reservation_status = "IN_USE" if status == "RETURN_PENDING" else "APPROVED"
        conditions: list[object] = [
            DeviceHandover.status == status,
            Reservation.status == reservation_status,
        ]
        if scope is not None:
            conditions.extend(
                [
                    Reservation.college_id == scope,
                    or_(
                        Lab.manager_id == self.principal.user_id,
                        College.manager_id == self.principal.user_id,
                    ),
                ]
            )
        page_ids = delayed_page_ids(
            select(Reservation.id)
            .join(DeviceHandover, DeviceHandover.reservation_id == Reservation.id)
            .join(Device, Device.id == Reservation.device_id)
            .outerjoin(Lab, Lab.id == Device.lab_id)
            .join(College, College.id == Device.college_id)
            .where(*conditions),
            Reservation.id,
            page=page,
            page_size=page_size,
        )
        stmt = (
            select(Reservation)
            .join(page_ids, page_ids.c.id == Reservation.id)
            .options(
                selectinload(Reservation.device).selectinload(Device.lab),
                selectinload(Reservation.days),
                selectinload(Reservation.user),
                selectinload(Reservation.handover),
                selectinload(Reservation.fault_repair),
            )
            .order_by(Reservation.id.desc())
        )
        reservations = list((await self.session.scalars(stmt)).all())
        count_conditions: list[object] = [
            DeviceHandover.status == status,
            Reservation.status == reservation_status,
        ]
        if scope is not None:
            count_conditions.extend(
                [
                    Reservation.college_id == scope,
                    or_(
                        Lab.manager_id == self.principal.user_id,
                        College.manager_id == self.principal.user_id,
                    ),
                ]
            )
        total = int(
            await self.session.scalar(
                select(func.count(Reservation.id))
                .join(DeviceHandover, DeviceHandover.reservation_id == Reservation.id)
                .join(Device, Device.id == Reservation.device_id)
                .outerjoin(Lab, Lab.id == Device.lab_id)
                .join(College, College.id == Device.college_id)
                .where(*count_conditions)
            )
            or 0
        )
        pages, truncated = page_metadata(total, page_size)
        return ReservationPage(
            items=[_reservation_data(item) for item in reservations],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            truncated=truncated,
        )
