from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
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
    ReservationPage,
    ReservationPlanRequest,
    ReservationPreflightData,
    WaitlistData,
)
from app.application.lifecycle import append_audit, change_device_status
from app.auth.security import Principal, college_scope
from app.core.errors import ApiError
from app.domain.reservation import ACTIVE_RESERVATION_STATUSES, RESERVATION_TRANSITIONS
from app.infrastructure.cache.cache import CacheService
from app.infrastructure.db.models import (
    College,
    CreditEvent,
    Device,
    IdempotencyKey,
    Lab,
    OutboxTask,
    RepairReport,
    Reservation,
    ReservationBlackout,
    ReservationInspection,
    ReservationItem,
    ReservationWaitlist,
    User,
)


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _date_at_end(value: date) -> datetime:
    return datetime.combine(value, time.max)


def request_hash(payload: ReservationPlanRequest) -> str:
    canonical = payload.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _segments(values: Iterable[date]) -> list[list[date]]:
    ordered = sorted(set(values))
    if not ordered:
        return []
    result: list[list[date]] = [[ordered[0]]]
    for current in ordered[1:]:
        if current == result[-1][-1] + timedelta(days=1):
            result[-1].append(current)
        else:
            result.append([current])
    return result


def _device_summary(device: Device) -> DeviceSummary:
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
    )


def _reservation_data(reservation: Reservation) -> ReservationData:
    user = reservation.__dict__.get("user")
    inspections = reservation.__dict__.get("inspections") or []
    inspection = inspections[-1] if inspections else None
    return ReservationData(
        id=reservation.id,
        device_id=reservation.device_id,
        device_name=reservation.device.name if reservation.device else "",
        user_id=reservation.user_id,
        username=user.username if user else None,
        real_name=user.real_name if user else None,
        purpose=reservation.purpose,
        start_date=reservation.start_date,
        end_date=reservation.end_date,
        dates=sorted(item.reservation_date for item in reservation.days),
        status=reservation.status,
        batch_id=reservation.batch_id,
        need_approval=reservation.device.need_approval if reservation.device else False,
        created_at=reservation.created_at,
        check_in_at=reservation.check_in_at,
        check_out_at=reservation.check_out_at,
        reject_reason=reservation.reject_reason,
        inspection_condition=inspection.condition if inspection else None,
        inspection_note=inspection.note if inspection else None,
    )


class ReservationService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        max_days: int = 31,
        user_active_limit: int = 10,
        user_days_limit: int = 31,
        credit_block_threshold: int = 60,
        credit_block_days: int = 7,
        cache: CacheService | None = None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.max_days = max_days
        self.user_active_limit = user_active_limit
        self.user_days_limit = user_days_limit
        self.credit_block_threshold = credit_block_threshold
        self.credit_block_days = credit_block_days
        self.cache = cache

    def _college_id(self) -> int | None:
        return college_scope(self.principal)

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
        cursor: int | None = None,
        include_meta: bool = False,
    ) -> tuple[list[DeviceSummary], int] | tuple[list[DeviceSummary], int, int | None, bool]:
        if page != 1 and cursor is None:
            raise ApiError("CURSOR_REQUIRED", "深页查询必须携带上一页游标", 422)
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
                        "cursor": cursor,
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
                    items, total, next_cursor, has_more = await self._list_devices_from_db(
                        search=search,
                        lab_id=lab_id,
                        status=status,
                        page=page,
                        page_size=page_size,
                        cursor=cursor,
                    )
                    return {
                        "items": [item.model_dump(mode="json") for item in items],
                        "total": total,
                        "next_cursor": next_cursor,
                        "has_more": has_more,
                    }

                raw = await self.cache.get_or_set_json(key, load)
                result = (
                    [DeviceSummary.model_validate(item) for item in raw.get("items", [])],
                    int(raw.get("total", 0)),
                    raw.get("next_cursor"),
                    bool(raw.get("has_more", False)),
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
            cursor=cursor,
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
        cursor: int | None,
    ) -> tuple[list[DeviceSummary], int, int | None, bool]:
        scope = self._college_id()
        conditions = [Device.status != "DELETED"]
        if scope is not None:
            conditions.append(Device.college_id == scope)
        if search:
            like = f"%{search.strip()}%"
            conditions.append(or_(Device.name.like(like), Device.model.like(like)))
        if lab_id is not None:
            conditions.append(Device.lab_id == lab_id)
        if status:
            conditions.append(Device.status == status)
        list_stmt = select(Device)
        count_stmt = select(func.count(Device.id)).select_from(Device)
        if self.principal.is_lab_admin and not self.principal.is_system_admin:
            list_stmt = list_stmt.outerjoin(Lab, Lab.id == Device.lab_id).join(
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
        query_conditions = list(conditions)
        if cursor is not None:
            query_conditions.append(Device.id < cursor)
        stmt = (
            list_stmt.options(
                selectinload(Device.lab),
                selectinload(Device.college),
                selectinload(Device.category),
            )
            .where(*query_conditions)
            .order_by(Device.id.desc())
            .offset((page - 1) * page_size if cursor is None else 0)
            .limit(page_size + 1)
        )
        devices = list((await self.session.scalars(stmt)).all())
        has_more = len(devices) > page_size
        if has_more:
            devices = devices[:page_size]
        return (
            [_device_summary(device) for device in devices],
            total,
            int(devices[-1].id) if has_more and devices else None,
            has_more,
        )

    async def get_device(self, device_id: int) -> DeviceDetail:
        device = await self._load_device(device_id)
        return DeviceDetail(
            **_device_summary(device).model_dump(),
            description=device.description,
            location=device.lab.location if device.lab else None,
        )

    async def availability(
        self,
        device_id: int,
        start_date: date,
        end_date: date,
    ) -> list[AvailabilityDay]:
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
        blackout = await self._blocked_dates(
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
            result.append(
                AvailabilityDay(
                    date=current,
                    available=row is None and current not in blackout and not blocked,
                    reservation_id=row[0] if row else None,
                    status=(
                        row[1]
                        if row
                        else (
                            "BLACKOUT"
                            if current in blackout
                            else device.status
                            if blocked
                            else None
                        )
                    ),
                )
            )
            current += timedelta(days=1)
        return result

    async def preflight(self, plan: ReservationPlanRequest) -> ReservationPreflightData:
        device = await self._load_device(plan.device_id)
        dates = plan.requested_dates()
        self._validate_dates(device, dates)
        occupied = await self._occupied(device.id, dates)
        blackout = await self._blocked_dates(device, dates)
        conflicts = [
            ReservationConflict(
                date=current,
                reason="设备已有有效预约",
                reservation_id=row[0],
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
        return ReservationPreflightData(
            device=_device_summary(device),
            requested_dates=dates,
            available_dates=[current for current in dates if current not in conflict_dates],
            conflicts=conflicts,
            all_available=not conflicts,
        )

    def _validate_dates(self, device: Device, dates: list[date]) -> None:
        if not dates:
            raise ApiError("DATE_RANGE_EMPTY", "至少选择一个预约日期", 422)
        if len(dates) > min(self.max_days, device.max_reservation_days):
            raise ApiError(
                "DATE_RANGE_TOO_LARGE",
                f"该设备单次最多预约 {min(self.max_days, device.max_reservation_days)} 天",
                422,
            )
        if min(dates) < date.today():
            raise ApiError("DATE_IN_PAST", "不能预约过去的日期", 422)

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
        return {
            row[0]: (int(row[1]), str(row[2])) for row in (await self.session.execute(stmt)).all()
        }

    async def _blocked_dates(
        self,
        device: Device,
        dates: list[date],
    ) -> dict[date, str]:
        if not dates:
            return {}
        scope_filters = [
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
        ]
        rows = list(
            (
                await self.session.execute(
                    select(ReservationBlackout.blocked_date, ReservationBlackout.reason).where(
                        ReservationBlackout.active.is_(True),
                        ReservationBlackout.blocked_date.in_(dates),
                        or_(*scope_filters),
                    )
                )
            ).all()
        )
        return {row[0]: str(row[1]) for row in rows}

    async def join_waitlist(
        self,
        *,
        device_id: int,
        reservation_date: date,
        purpose: str,
    ) -> WaitlistData:
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
                ReservationWaitlist.status == "WAITING",
            )
        )
        if existing is not None:
            raise ApiError("WAITLIST_EXISTS", "你已经在该日期的候补队列中", 409)
        entry = ReservationWaitlist(
            device_id=device_id,
            college_id=device.college_id,
            user_id=self.principal.user_id,
            reservation_date=reservation_date,
            purpose=purpose.strip(),
            status="WAITING",
            created_at=utcnow_naive(),
        )
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
            status=entry.status,
            created_at=entry.created_at,
        )

    async def list_waitlist(self) -> list[WaitlistData]:
        conditions = [
            ReservationWaitlist.user_id == self.principal.user_id,
            ReservationWaitlist.status.in_(("WAITING", "NOTIFIED")),
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
        return [
            WaitlistData(
                id=entry.id,
                device_id=entry.device_id,
                device_name=name,
                reservation_date=entry.reservation_date,
                purpose=entry.purpose,
                status=entry.status,
                created_at=entry.created_at,
            )
            for entry, name in rows
        ]

    async def cancel_waitlist(self, entry_id: int) -> None:
        result = await self.session.execute(
            update(ReservationWaitlist)
            .where(
                ReservationWaitlist.id == entry_id,
                ReservationWaitlist.user_id == self.principal.user_id,
                ReservationWaitlist.status.in_(("WAITING", "NOTIFIED")),
            )
            .values(status="CANCELLED")
        )
        if result.rowcount != 1:
            raise ApiError("WAITLIST_NOT_FOUND", "候补申请不存在或已处理", 404)
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=self._college_id(),
            action="WAITLIST_CANCEL",
            target_type="WAITLIST",
            target_id=entry_id,
        )
        await self.session.commit()

    async def create(
        self,
        plan: ReservationPlanRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ReservationCreateData:
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
            active_count = int(
                await self.session.scalar(
                    select(func.count(Reservation.id)).where(
                        Reservation.user_id == self.principal.user_id,
                        Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
                    )
                )
                or 0
            )
            if active_count >= self.user_active_limit:
                raise ApiError("RESERVATION_LIMIT", "当前有效预约已达到上限", 409)

        preflight = await self.preflight(plan)
        if preflight.conflicts and plan.commit_mode == "all_or_nothing":
            raise ApiError(
                "RESERVATION_CONFLICT",
                "所选日期存在冲突，请查看冲突日期后重新提交",
                409,
                data=preflight.model_dump(mode="json"),
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
        segments = _segments(selected)
        active_limit = self.user_active_limit
        if not self.principal.is_system_admin:
            active_count = int(
                await self.session.scalar(
                    select(func.count(Reservation.id)).where(
                        Reservation.user_id == self.principal.user_id,
                        Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
                    )
                )
                or 0
            )
            if active_count + len(segments) > active_limit:
                raise ApiError(
                    "RESERVATION_LIMIT",
                    f"当前有效预约最多保留 {active_limit} 条",
                    409,
                )
            active_days = int(
                await self.session.scalar(
                    select(func.count(ReservationItem.id))
                    .join(Reservation, Reservation.id == ReservationItem.reservation_id)
                    .where(
                        Reservation.user_id == self.principal.user_id,
                        Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
                    )
                )
                or 0
            )
            if active_days + len(selected) > self.user_days_limit:
                raise ApiError(
                    "RESERVATION_DAY_LIMIT",
                    f"当前有效预约累计最多保留 {self.user_days_limit} 天",
                    409,
                )
        batch_id = uuid4().hex if explicit_batch or len(segments) > 1 else None
        created: list[ReservationData] = []
        device = await self._load_device(plan.device_id)
        status = "PENDING" if device.need_approval else "APPROVED"
        try:
            for segment in segments:
                reservation_now = utcnow_naive()
                reservation = Reservation(
                    college_id=device.college_id,
                    user_id=self.principal.user_id,
                    device_id=device.id,
                    purpose=plan.purpose.strip(),
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
                                else "预约已确认，请按预约日期到场签到。"
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
        cursor: int | None = None,
    ) -> ReservationPage:
        if page != 1 and cursor is None:
            raise ApiError("CURSOR_REQUIRED", "深页查询必须携带上一页游标", 422)
        base_conditions = [Reservation.user_id == self.principal.user_id]
        scope = self._college_id()
        if scope is not None:
            base_conditions.append(Reservation.college_id == scope)
        if status:
            base_conditions.append(Reservation.status == status)
        total = int(
            await self.session.scalar(select(func.count(Reservation.id)).where(*base_conditions))
            or 0
        )
        conditions = list(base_conditions)
        if cursor is not None:
            conditions.append(Reservation.id < cursor)
        # Fetch one sentinel row on every page so the UI can build its next
        # cursor without issuing a COUNT-based deep OFFSET query.
        limit = page_size + 1
        # The first page uses the same primary-key order as subsequent keyset
        # pages.  Mixing start_date ordering with an id cursor can duplicate
        # or skip rows when records are inserted between requests.
        order_columns = (Reservation.id.desc(),)
        stmt = (
            select(Reservation)
            .options(
                selectinload(Reservation.device),
                selectinload(Reservation.days),
                selectinload(Reservation.inspections),
            )
            .where(*conditions)
            .order_by(*order_columns)
            .offset((page - 1) * page_size if cursor is None else 0)
            .limit(limit)
        )
        reservations = list((await self.session.scalars(stmt)).all())
        has_more = len(reservations) > page_size
        if has_more:
            reservations = reservations[:page_size]
        return ReservationPage(
            items=[_reservation_data(item) for item in reservations],
            total=total,
            page=page,
            page_size=page_size,
            next_cursor=int(reservations[-1].id) if has_more and reservations else None,
            has_more=has_more,
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
            )
            .where(Reservation.id == reservation_id)
        )
        if reservation is None:
            raise ApiError("RESERVATION_NOT_FOUND", "预约不存在", 404)
        return reservation

    async def _can_view(self, reservation: Reservation) -> bool:
        if self.principal.is_system_admin or reservation.user_id == self.principal.user_id:
            return self._college_id() is None or reservation.college_id == self._college_id()
        return await self._can_manage_device(reservation.device)

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

    async def approve(
        self,
        reservation_id: int,
        approve: bool,
        reason: str | None = None,
    ) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
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
        if not self.principal.is_lab_admin and not self.principal.is_system_admin:
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
        for reservation in reservations:
            if reservation.status != "PENDING":
                raise ApiError("INVALID_RESERVATION_STATE", "批量审批中存在非待审批预约", 409)
            if not await self._can_manage_device(reservation.device):
                raise ApiError("FORBIDDEN", "批量审批包含不在管理范围内的设备", 403)
            if reservation.device.status in {"MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED"}:
                raise ApiError("DEVICE_UNAVAILABLE", "批量审批中包含不可用设备", 409)
        now = utcnow_naive()
        for reservation in reservations:
            reservation.status = "APPROVED"
            reservation.approver_id = self.principal.user_id
            reservation.approved_at = now
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
            append_audit(
                self.session,
                user_id=self.principal.user_id,
                college_id=reservation.college_id,
                action="RESERVATION_APPROVE",
                target_type="RESERVATION",
                target_id=reservation.id,
            )
        await self.session.commit()
        return len(reservations)

    async def violate(self, reservation_id: int, reason: str) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
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
            content = f"设备“{device_name}”的预约已通过，请按预约日期到场使用。"
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
        return await self._transition_owned(reservation_id, "IN_USE", "预约首日才能签到")

    async def return_device(
        self,
        reservation_id: int,
        *,
        condition: str = "NORMAL",
        note: str | None = None,
    ) -> ReservationData:
        return await self._transition_owned(
            reservation_id,
            "COMPLETED",
            "预约结束日才能归还",
            condition=condition,
            note=note,
        )

    async def _transition_owned(
        self,
        reservation_id: int,
        target: str,
        day_error: str,
        *,
        condition: str | None = None,
        note: str | None = None,
    ) -> ReservationData:
        reservation = await self._load_reservation(reservation_id)
        if reservation.user_id != self.principal.user_id:
            raise ApiError("FORBIDDEN", "只能操作自己的预约", 403)
        if target == "IN_USE":
            if date.today() != reservation.start_date:
                raise ApiError("CHECK_IN_DAY_INVALID", day_error, 409)
        elif target == "COMPLETED":
            if date.today() != reservation.end_date:
                raise ApiError("RETURN_DAY_INVALID", day_error, 409)
            if condition not in {"NORMAL", "DAMAGED", "MISSING"}:
                raise ApiError("INSPECTION_INVALID", "归还验收状态无效", 422)
        if reservation.device.status in {"DISABLED", "OFFLINE", "RETIRED"} or (
            target == "IN_USE" and reservation.device.status == "MAINTENANCE"
        ):
            raise ApiError("DEVICE_UNAVAILABLE", "当前设备状态不允许履约操作", 409)
        allowed = [
            source for source, targets in RESERVATION_TRANSITIONS.items() if target in targets
        ]
        now = utcnow_naive()
        values: dict[str, object] = {"status": target}
        if target == "IN_USE":
            values["check_in_at"] = now
        else:
            values["check_out_at"] = now
        result = await self.session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status.in_(allowed),
                Reservation.user_id == self.principal.user_id,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise ApiError("INVALID_RESERVATION_STATE", "预约状态不允许此操作", 409)
        if target == "IN_USE":
            change_device_status(
                self.session,
                reservation.device,
                "IN_USE",
                operator_id=self.principal.user_id,
                reason="预约用户签到",
            )
            title = "预约已签到"
            content = f"设备“{reservation.device.name}”已开始使用。"
        else:
            inspection = ReservationInspection(
                reservation_id=reservation.id,
                device_id=reservation.device_id,
                user_id=self.principal.user_id,
                condition=condition or "NORMAL",
                note=note.strip() if note else None,
                created_at=now,
            )
            reservation.inspections.append(inspection)
            self.session.add(inspection)
            open_repairs = int(
                await self.session.scalar(
                    select(func.count(RepairReport.id)).where(
                        RepairReport.device_id == reservation.device_id,
                        RepairReport.status.in_(("PENDING", "PROCESSING")),
                    )
                )
                or 0
            )
            target_status = (
                "MAINTENANCE" if condition in {"DAMAGED", "MISSING"} or open_repairs else "IDLE"
            )
            change_device_status(
                self.session,
                reservation.device,
                target_status,
                operator_id=self.principal.user_id,
                reason=note
                or ("归还验收发现异常" if target_status == "MAINTENANCE" else "预约归还"),
            )
            title = "预约已归还"
            content = (
                f"设备“{reservation.device.name}”已完成归还。"
                if target_status == "IDLE"
                else (
                    f"设备“{reservation.device.name}”归还后仍有未完成报修，保持维护状态。"
                    if open_repairs and condition == "NORMAL"
                    else f"设备“{reservation.device.name}”归还验收发现异常，已进入维护状态。"
                )
            )
        self.session.add(
            OutboxTask(
                task_key=f"notification:reservation:{reservation.id}:{target.lower()}",
                task_type="NOTIFICATION",
                aggregate_key=f"reservation:{reservation.id}",
                college_id=reservation.college_id,
                payload={
                    "user_id": reservation.user_id,
                    "college_id": reservation.college_id,
                    "type": "RESERVATION_UPDATE",
                    "title": title,
                    "content": content,
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
            action="RESERVATION_CHECK_IN" if target == "IN_USE" else "RESERVATION_RETURN",
            target_type="RESERVATION",
            target_id=reservation.id,
            detail={"condition": condition, "note": note},
        )
        await self.session.commit()
        reservation.status = target
        if target == "IN_USE":
            reservation.check_in_at = now
        else:
            reservation.check_out_at = now
        return _reservation_data(reservation)

    async def pending_approvals(
        self,
        page: int = 1,
        page_size: int = 20,
        cursor: int | None = None,
    ) -> ReservationPage:
        if page != 1 and cursor is None:
            raise ApiError("CURSOR_REQUIRED", "深页查询必须携带上一页游标", 422)
        scope = self._college_id()
        if not self.principal.is_lab_admin and not self.principal.is_system_admin:
            raise ApiError("FORBIDDEN", "当前角色无审批权限", 403)
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
        if cursor is not None:
            conditions.append(Reservation.id < cursor)
        limit = page_size + 1
        order_columns = (Reservation.id.desc(),)
        stmt = (
            select(Reservation)
            .join(Device, Device.id == Reservation.device_id)
            .outerjoin(Lab, Lab.id == Device.lab_id)
            .join(College, College.id == Device.college_id)
            .options(
                selectinload(Reservation.device),
                selectinload(Reservation.days),
                selectinload(Reservation.user),
            )
            .where(*conditions)
            .order_by(*order_columns)
            .offset((page - 1) * page_size if cursor is None else 0)
            .limit(limit)
        )
        reservations = list((await self.session.scalars(stmt)).all())
        has_more = len(reservations) > page_size
        if has_more:
            reservations = reservations[:page_size]
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
        return ReservationPage(
            items=[_reservation_data(item) for item in reservations],
            total=total,
            page=page,
            page_size=page_size,
            next_cursor=int(reservations[-1].id) if has_more and reservations else None,
            has_more=has_more,
        )
