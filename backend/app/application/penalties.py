"""College-owned penalty policies, appeal decisions and overdue follow-up."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.lifecycle import append_audit
from app.application.penalty_processing import (
    _cancel_other_reservations,
    _credit_delta,
    enqueue_notification,
    utcnow_naive,
)
from app.auth.security import Principal
from app.core.errors import ApiError
from app.infrastructure.db.models import (
    College,
    CollegeCreditAccount,
    Device,
    Lab,
    OutboxTask,
    PenaltyAppeal,
    PenaltyCase,
    PenaltyGraceBounds,
    PenaltyRuleVersion,
    Reservation,
    ReservationBookingRestriction,
    ReservationOverdue,
    ReservationOverdueFollowUp,
    Role,
    User,
    user_roles,
)
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset

DEFAULT_GRACE_MIN_DAYS = 0
DEFAULT_GRACE_MAX_DAYS = 30


def _validate_tiers(tiers: dict[str, Any]) -> dict[str, list[dict[str, int]]]:
    allowed = {"NO_SHOW", "OVERDUE_RETURN", "MANUAL_VIOLATION"}
    if not isinstance(tiers, dict) or set(tiers) - allowed:
        raise ApiError("PENALTY_RULE_INVALID", "违规类型配置无效", 422)
    normalized: dict[str, list[dict[str, int]]] = {}
    for violation_type in allowed:
        rows = tiers.get(violation_type, [])
        if not isinstance(rows, list) or len(rows) > 20:
            raise ApiError("PENALTY_RULE_INVALID", "每类违规最多配置 20 个处罚阶梯", 422)
        parsed: list[dict[str, int]] = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ApiError("PENALTY_RULE_INVALID", "处罚阶梯格式无效", 422)
            occurrence = row.get("occurrence", index)
            points = row.get("points", 0)
            block_days = row.get("block_days", 0)
            if (
                not isinstance(occurrence, int)
                or occurrence != index
                or not isinstance(points, int)
                or not 0 <= points <= 100
                or not isinstance(block_days, int)
                or not 0 <= block_days <= 365
            ):
                raise ApiError(
                    "PENALTY_RULE_INVALID",
                    "阶梯次数必须从 1 连续递增；扣分范围 0–100，预约暂停范围 0–365 天",
                    422,
                )
            parsed.append({"occurrence": occurrence, "points": points, "block_days": block_days})
        normalized[violation_type] = parsed
    if not normalized["NO_SHOW"] or not normalized["OVERDUE_RETURN"]:
        raise ApiError(
            "PENALTY_RULE_INVALID",
            "爽约和逾期未还都需要至少配置一个处罚阶梯",
            422,
        )
    return normalized


class PenaltyService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def _college(self, college_id: int | None = None) -> int:
        resolved = college_id if college_id is not None else self.principal.college_id
        if resolved is None:
            raise ApiError("COLLEGE_REQUIRED", "账号尚未归属学院", 403)
        if not self.principal.is_system_admin and self.principal.college_id != resolved:
            raise ApiError("FORBIDDEN", "只能访问本学院数据", 403)
        return int(resolved)

    async def _is_college_head(self, college_id: int) -> bool:
        return bool(
            await self.session.scalar(
                select(College.id).where(
                    College.id == college_id,
                    College.manager_id == self.principal.user_id,
                )
            )
        )

    async def _require_college_admin(self, college_id: int) -> None:
        is_head = await self._is_college_head(college_id)
        is_lab_admin = (
            "LAB_ADMIN" in self.principal.roles and self.principal.college_id == college_id
        )
        if self.principal.is_system_admin or not (is_head or is_lab_admin):
            raise ApiError("FORBIDDEN", "只有本学院负责人或本院管理员可以操作", 403)

    async def _require_policy_owner(self, college_id: int) -> None:
        if self.principal.is_system_admin or not await self._is_college_head(college_id):
            raise ApiError("FORBIDDEN", "只有本学院负责人可以制定处罚规则", 403)

    async def grace_bounds(self) -> dict[str, int]:
        if not self.principal.is_system_admin:
            raise ApiError("FORBIDDEN", "只有系统管理员可以查看全校宽限期范围", 403)
        row = await self.session.get(PenaltyGraceBounds, 1)
        if row is None:
            return {"minimum_days": DEFAULT_GRACE_MIN_DAYS, "maximum_days": DEFAULT_GRACE_MAX_DAYS}
        return {"minimum_days": row.minimum_days, "maximum_days": row.maximum_days}

    async def update_grace_bounds(self, minimum_days: int, maximum_days: int) -> dict[str, int]:
        if not self.principal.is_system_admin:
            raise ApiError("FORBIDDEN", "只有系统管理员可以设置全校宽限期范围", 403)
        if minimum_days < 0 or maximum_days < minimum_days or maximum_days > 365:
            raise ApiError(
                "GRACE_BOUNDS_INVALID", "宽限期范围必须满足 0 ≤ 最小值 ≤ 最大值 ≤ 365", 422
            )
        row = await self.session.scalar(
            select(PenaltyGraceBounds).where(PenaltyGraceBounds.id == 1).with_for_update()
        )
        now = utcnow_naive()
        previous = (
            {"minimum_days": row.minimum_days, "maximum_days": row.maximum_days}
            if row is not None
            else {"minimum_days": DEFAULT_GRACE_MIN_DAYS, "maximum_days": DEFAULT_GRACE_MAX_DAYS}
        )
        if row is None:
            row = PenaltyGraceBounds(
                id=1,
                minimum_days=minimum_days,
                maximum_days=maximum_days,
                updated_by=self.principal.user_id,
                updated_at=now,
            )
            self.session.add(row)
        else:
            row.minimum_days = minimum_days
            row.maximum_days = maximum_days
            row.updated_by = self.principal.user_id
            row.updated_at = now
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=None,
            action="PENALTY_GRACE_BOUNDS_UPDATE",
            target_type="PENALTY_GRACE_BOUNDS",
            target_id=1,
            detail={
                "before": previous,
                "after": {"minimum_days": minimum_days, "maximum_days": maximum_days},
            },
        )
        await self.session.commit()
        return {"minimum_days": minimum_days, "maximum_days": maximum_days}

    async def get_policy(self) -> dict[str, Any]:
        college_id = await self._college()
        is_head = await self._is_college_head(college_id)
        can_manage = is_head and not self.principal.is_system_admin
        can_review = not self.principal.is_system_admin and (
            is_head
            or ("LAB_ADMIN" in self.principal.roles and self.principal.college_id == college_id)
        )
        bounds = await self.session.get(PenaltyGraceBounds, 1)
        minimum_days = bounds.minimum_days if bounds else DEFAULT_GRACE_MIN_DAYS
        maximum_days = bounds.maximum_days if bounds else DEFAULT_GRACE_MAX_DAYS
        row = await self.session.scalar(
            select(PenaltyRuleVersion)
            .where(PenaltyRuleVersion.college_id == college_id)
            .order_by(PenaltyRuleVersion.version.desc())
            .limit(1)
        )
        if row is None:
            return {
                "college_id": college_id,
                "version": None,
                "effective_at": None,
                "grace_days": None,
                "tiers": {"NO_SHOW": [], "OVERDUE_RETURN": [], "MANUAL_VIOLATION": []},
                "can_manage": can_manage,
                "can_review": can_review,
                "minimum_grace_days": minimum_days,
                "maximum_grace_days": maximum_days,
            }
        return {
            "college_id": row.college_id,
            "version": row.version,
            "effective_at": row.effective_at,
            "grace_days": row.grace_days,
            "tiers": row.tiers,
            "can_manage": can_manage,
            "can_review": can_review,
            "minimum_grace_days": minimum_days,
            "maximum_grace_days": maximum_days,
        }

    async def save_policy(self, grace_days: int, tiers: dict[str, Any]) -> dict[str, Any]:
        college_id = await self._college()
        await self._require_policy_owner(college_id)
        normalized_tiers = _validate_tiers(tiers)
        bounds = await self.session.get(PenaltyGraceBounds, 1)
        minimum = bounds.minimum_days if bounds else DEFAULT_GRACE_MIN_DAYS
        maximum = bounds.maximum_days if bounds else DEFAULT_GRACE_MAX_DAYS
        if not minimum <= grace_days <= maximum:
            raise ApiError(
                "GRACE_PERIOD_OUT_OF_RANGE",
                f"逾期宽限期必须在 {minimum} 到 {maximum} 个自然日之间",
                422,
            )
        college = await self.session.scalar(
            select(College).where(College.id == college_id).with_for_update()
        )
        if college is None:
            raise ApiError("COLLEGE_NOT_FOUND", "学院不存在", 404)
        current = await self.session.scalar(
            select(PenaltyRuleVersion)
            .where(PenaltyRuleVersion.college_id == college_id)
            .order_by(PenaltyRuleVersion.version.desc())
            .limit(1)
            .with_for_update()
        )
        now = utcnow_naive()
        row = PenaltyRuleVersion(
            college_id=college_id,
            version=(current.version + 1) if current else 1,
            effective_at=now,
            grace_days=grace_days,
            tiers=normalized_tiers,
            created_by=self.principal.user_id,
            created_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=college_id,
            action="PENALTY_POLICY_VERSION_CREATE",
            target_type="PENALTY_RULE_VERSION",
            target_id=row.id,
            detail={
                "version": row.version,
                "grace_days": grace_days,
                "tiers": normalized_tiers,
                "previous_version": current.version if current else None,
            },
        )
        await self.session.commit()
        return {
            "college_id": college_id,
            "version": row.version,
            "effective_at": row.effective_at,
            "grace_days": row.grace_days,
            "tiers": row.tiers,
            "can_manage": True,
            "can_review": True,
            "minimum_grace_days": minimum,
            "maximum_grace_days": maximum,
        }

    async def my_cases(self) -> list[dict[str, Any]]:
        college_id = await self._college()
        rows = list(
            (
                await self.session.execute(
                    select(PenaltyCase, Reservation.id, Device.name, Lab.name)
                    .join(Reservation, Reservation.id == PenaltyCase.reservation_id)
                    .join(Device, Device.id == PenaltyCase.device_id)
                    .outerjoin(Lab, Lab.id == PenaltyCase.lab_id)
                    .where(
                        PenaltyCase.user_id == self.principal.user_id,
                        PenaltyCase.college_id == college_id,
                    )
                    .order_by(PenaltyCase.applied_at.desc(), PenaltyCase.id.desc())
                    .limit(100)
                )
            ).all()
        )
        result: list[dict[str, Any]] = []
        for case, reservation_id, device_name, lab_name in rows:
            appeals = list(
                (
                    await self.session.scalars(
                        select(PenaltyAppeal)
                        .where(PenaltyAppeal.penalty_case_id == case.id)
                        .order_by(PenaltyAppeal.attempt_number)
                    )
                ).all()
            )
            result.append(
                {
                    "id": case.id,
                    "reservation_id": reservation_id,
                    "violation_type": case.violation_type,
                    "reason": case.reason,
                    "event_at": case.event_at,
                    "occurrence_number": case.occurrence_number,
                    "points_delta": case.points_delta,
                    "reservation_block_days": case.reservation_block_days,
                    "status": case.status,
                    "applied_at": case.applied_at,
                    "device_name": device_name,
                    "lab_name": lab_name,
                    "appeal_count": len(appeals),
                    "appeals": [self._appeal_data(row) for row in appeals],
                }
            )
        return result

    async def my_balance(self) -> dict[str, int]:
        college_id = await self._college()
        points = await self.session.scalar(
            select(CollegeCreditAccount.points).where(
                CollegeCreditAccount.user_id == self.principal.user_id,
                CollegeCreditAccount.college_id == college_id,
            )
        )
        if points is None:
            points = 100
        return {"college_id": college_id, "points": int(points)}

    async def college_cases(self, page: int, page_size: int) -> dict[str, Any]:
        college_id = await self._college()
        await self._require_college_admin(college_id)
        page_offset(page, page_size)
        base = select(PenaltyCase.id).where(PenaltyCase.college_id == college_id)
        total = int(
            await self.session.scalar(
                select(func.count(PenaltyCase.id)).where(PenaltyCase.college_id == college_id)
            )
            or 0
        )
        page_ids = delayed_page_ids(
            base,
            PenaltyCase.id,
            page=page,
            page_size=page_size,
            name="penalty_case_page_ids",
        )
        rows = list(
            (
                await self.session.execute(
                    select(PenaltyCase, User.real_name, User.username, Device.name, Lab.name)
                    .join(User, User.id == PenaltyCase.user_id)
                    .join(Device, Device.id == PenaltyCase.device_id)
                    .outerjoin(Lab, Lab.id == PenaltyCase.lab_id)
                    .join(page_ids, page_ids.c.id == PenaltyCase.id)
                    .order_by(PenaltyCase.applied_at.desc(), PenaltyCase.id.desc())
                )
            ).all()
        )
        pages, truncated = page_metadata(total, page_size)
        return {
            "items": [
                {
                    "id": case.id,
                    "reservation_id": case.reservation_id,
                    "user_id": case.user_id,
                    "user_name": real_name or username,
                    "violation_type": case.violation_type,
                    "reason": case.reason,
                    "event_at": case.event_at,
                    "occurrence_number": case.occurrence_number,
                    "points_delta": case.points_delta,
                    "reservation_block_days": case.reservation_block_days,
                    "status": case.status,
                    "applied_at": case.applied_at,
                    "device_name": device_name,
                    "lab_name": lab_name,
                }
                for case, real_name, username, device_name, lab_name in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "truncated": truncated,
        }

    @staticmethod
    def _appeal_data(row: PenaltyAppeal) -> dict[str, Any]:
        return {
            "id": row.id,
            "penalty_case_id": row.penalty_case_id,
            "attempt_number": row.attempt_number,
            "reason": row.reason,
            "evidence": row.evidence,
            "status": row.status,
            "reviewer_id": row.reviewer_id,
            "result": row.result,
            "result_reason": row.result_reason,
            "submitted_at": row.submitted_at,
            "reviewed_at": row.reviewed_at,
            "adjusted_points_delta": row.adjusted_points_delta,
            "adjusted_block_days": row.adjusted_block_days,
        }

    async def list_appeals(
        self,
        pending_only: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        college_id = await self._college()
        await self._require_college_admin(college_id)
        page_offset(page, page_size)
        conditions = [PenaltyAppeal.college_id == college_id]
        if pending_only:
            conditions.append(PenaltyAppeal.status == "PENDING")
        base = select(PenaltyAppeal.id).where(*conditions)
        total = int(
            await self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        )
        page_ids = delayed_page_ids(
            base,
            PenaltyAppeal.id,
            page=page,
            page_size=page_size,
            name="penalty_appeal_page_ids",
        )
        rows = list(
            (
                await self.session.execute(
                    select(PenaltyAppeal, PenaltyCase, User.real_name, User.username, Device.name)
                    .join(PenaltyCase, PenaltyCase.id == PenaltyAppeal.penalty_case_id)
                    .join(User, User.id == PenaltyAppeal.user_id)
                    .join(Device, Device.id == PenaltyCase.device_id)
                    .join(page_ids, page_ids.c.id == PenaltyAppeal.id)
                    .order_by(PenaltyAppeal.submitted_at.asc(), PenaltyAppeal.id.asc())
                )
            ).all()
        )
        pages, truncated = page_metadata(total, page_size)
        return {
            "items": [
                {
                    **self._appeal_data(appeal),
                    "user_name": real_name or username,
                    "violation_type": case.violation_type,
                    "reservation_id": case.reservation_id,
                    "device_name": device_name,
                    "penalty_points_delta": case.points_delta,
                    "penalty_block_days": case.reservation_block_days,
                    "penalty_status": case.status,
                }
                for appeal, case, real_name, username, device_name in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "truncated": truncated,
        }

    async def submit_appeal(
        self,
        case_id: int,
        *,
        reason: str,
        evidence: str | None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise ApiError("APPEAL_REASON_REQUIRED", "请填写申诉理由", 422)
        case = await self.session.scalar(
            select(PenaltyCase).where(PenaltyCase.id == case_id).with_for_update()
        )
        if case is None or case.user_id != self.principal.user_id:
            raise ApiError("PENALTY_NOT_FOUND", "处罚记录不存在", 404)
        if case.status == "REVOKED":
            raise ApiError("PENALTY_NOT_ACTIVE", "该处罚已撤销，不能继续申诉", 409)
        existing = list(
            (
                await self.session.scalars(
                    select(PenaltyAppeal)
                    .where(PenaltyAppeal.penalty_case_id == case_id)
                    .order_by(PenaltyAppeal.attempt_number)
                    .with_for_update()
                )
            ).all()
        )
        if existing and existing[-1].status == "PENDING":
            raise ApiError("APPEAL_PENDING", "当前申诉尚未复核", 409)
        if len(existing) >= 3:
            raise ApiError("APPEAL_LIMIT_REACHED", "同一处罚最多申诉三次", 409)
        now = utcnow_naive()
        appeal = PenaltyAppeal(
            penalty_case_id=case.id,
            user_id=case.user_id,
            college_id=case.college_id,
            attempt_number=len(existing) + 1,
            reason=reason.strip(),
            evidence=evidence.strip() if evidence and evidence.strip() else None,
            status="PENDING",
            submitted_at=now,
            created_at=now,
        )
        self.session.add(appeal)
        await self.session.flush()
        manager_id = await self.session.scalar(
            select(College.manager_id).where(College.id == case.college_id)
        )
        if appeal.attempt_number > 1:
            first_reviewer_id = await self.session.scalar(
                select(PenaltyAppeal.reviewer_id).where(
                    PenaltyAppeal.penalty_case_id == case.id,
                    PenaltyAppeal.attempt_number == 1,
                )
            )
            admin_ids = {int(first_reviewer_id)} if first_reviewer_id is not None else set()
        else:
            admin_ids = set(
                int(value)
                for value in (
                    await self.session.scalars(
                        select(User.id)
                        .join(user_roles, user_roles.c.user_id == User.id)
                        .join(Role, Role.id == user_roles.c.role_id)
                        .where(
                            User.college_id == case.college_id,
                            User.status == 1,
                            Role.role_code == "LAB_ADMIN",
                        )
                    )
                ).all()
            )
            if manager_id is not None:
                admin_ids.add(int(manager_id))
            if case.confirmed_by is not None:
                admin_ids.discard(int(case.confirmed_by))
            admin_ids.discard(int(case.user_id))
        if admin_ids:
            admin_ids = set(
                int(value)
                for value in (
                    await self.session.scalars(
                        select(User.id).where(
                            User.id.in_(admin_ids),
                            User.status == 1,
                        )
                    )
                ).all()
            )
        for recipient_id in sorted(admin_ids):
            enqueue_notification(
                self.session,
                task_key=f"notification:penalty-appeal:{appeal.id}:submitted:user:{recipient_id}",
                user_id=recipient_id,
                college_id=case.college_id,
                title="收到新的处罚申诉",
                content=(
                    f"用户已对处罚 #{case.id} 提交第 "
                    f"{appeal.attempt_number} 次申诉，请在申诉列表复核。"
                ),
                related_id=appeal.id,
                related_type="PENALTY_APPEAL",
            )
        self.session.add(
            OutboxTask(
                task_key=f"timeout:penalty-appeal:{appeal.id}:reminder",
                task_type="PENALTY_APPEAL_REMINDER",
                aggregate_key=f"penalty-appeal:{appeal.id}",
                college_id=case.college_id,
                payload={"appeal_id": appeal.id},
                execute_at=now + timedelta(days=3),
            )
        )
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=case.college_id,
            action="PENALTY_APPEAL_SUBMIT",
            target_type="PENALTY_APPEAL",
            target_id=appeal.id,
            detail={"penalty_case_id": case.id, "attempt_number": appeal.attempt_number},
        )
        await self.session.commit()
        return self._appeal_data(appeal)

    async def review_appeal(
        self,
        appeal_id: int,
        *,
        result: str,
        result_reason: str,
        points_deduction: int | None,
        block_days: int | None,
    ) -> dict[str, Any]:
        case_id = await self.session.scalar(
            select(PenaltyAppeal.penalty_case_id).where(PenaltyAppeal.id == appeal_id)
        )
        if case_id is None:
            raise ApiError("APPEAL_NOT_FOUND", "申诉记录不存在", 404)
        case_user_id = await self.session.scalar(
            select(PenaltyCase.user_id).where(PenaltyCase.id == case_id)
        )
        if case_user_id is None:
            raise ApiError("PENALTY_NOT_FOUND", "关联处罚记录不存在", 404)
        locked_user = await self.session.scalar(
            select(User).where(User.id == case_user_id).with_for_update()
        )
        if locked_user is None:
            raise ApiError("USER_NOT_FOUND", "处罚用户不存在", 404)
        case = await self.session.scalar(
            select(PenaltyCase).where(PenaltyCase.id == case_id).with_for_update()
        )
        if case is None:
            raise ApiError("PENALTY_NOT_FOUND", "关联处罚记录不存在", 404)
        appeal = await self.session.scalar(
            select(PenaltyAppeal).where(PenaltyAppeal.id == appeal_id).with_for_update()
        )
        if appeal is None:
            raise ApiError("APPEAL_NOT_FOUND", "申诉记录不存在", 404)
        if appeal.penalty_case_id != case.id:
            raise ApiError("APPEAL_CASE_CHANGED", "申诉关联处罚已变化，请重试", 409)
        await self._require_college_admin(appeal.college_id)
        if appeal.status != "PENDING":
            raise ApiError("APPEAL_ALREADY_REVIEWED", "该申诉已复核", 409)
        if appeal.user_id == self.principal.user_id:
            raise ApiError("APPEAL_REVIEW_CONFLICT", "不能复核自己提交的申诉", 403)
        if case.confirmed_by == self.principal.user_id:
            raise ApiError("APPEAL_REVIEW_CONFLICT", "确认违规事实的人不能复核该处罚申诉", 403)
        if appeal.attempt_number > 1:
            first_reviewer_id = await self.session.scalar(
                select(PenaltyAppeal.reviewer_id).where(
                    PenaltyAppeal.penalty_case_id == case.id,
                    PenaltyAppeal.attempt_number == 1,
                )
            )
            if first_reviewer_id != self.principal.user_id:
                raise ApiError(
                    "APPEAL_REVIEWER_FIXED", "同一处罚的后续申诉由首次复核负责人处理", 403
                )
        if result not in {"MAINTAIN", "ADJUST", "REVOKE"}:
            raise ApiError("APPEAL_RESULT_INVALID", "复核结果无效", 422)
        if not result_reason.strip():
            raise ApiError("APPEAL_REASON_REQUIRED", "请填写处理理由", 422)
        if result == "ADJUST" and (points_deduction is None or block_days is None):
            raise ApiError("APPEAL_ADJUSTMENT_REQUIRED", "调整处罚时需明确扣分和暂停天数", 422)
        if result == "ADJUST" and block_days and case.lab_id is None:
            raise ApiError("PENALTY_LAB_MISSING", "该处罚未关联实验室，不能增加实验室预约限制", 409)
        if points_deduction is not None and not 0 <= points_deduction <= 100:
            raise ApiError("PENALTY_VALUE_INVALID", "扣分范围为 0 到 100", 422)
        if block_days is not None and not 0 <= block_days <= 365:
            raise ApiError("PENALTY_VALUE_INVALID", "预约暂停范围为 0 到 365 天", 422)

        now = utcnow_naive()
        old_points_delta = case.points_delta
        old_block_days = case.reservation_block_days
        if result == "REVOKE":
            target_points_delta = 0
            target_block_days = 0
            case.status = "REVOKED"
            case.revoked_at = now
        elif result == "ADJUST":
            target_points_delta = -(points_deduction or 0)
            target_block_days = block_days or 0
            case.status = "ACTIVE"
            case.revoked_at = None
        else:
            target_points_delta = old_points_delta
            target_block_days = old_block_days
        if target_points_delta != old_points_delta:
            actual_delta = await _credit_delta(
                self.session,
                user=locked_user,
                college_id=case.college_id,
                reservation_id=case.reservation_id,
                delta=target_points_delta - old_points_delta,
                reason=f"申诉复核调整处罚 #{case.id}：{result_reason.strip()}"[:500],
                operator_id=self.principal.user_id,
                event_type="PENALTY_APPEAL_ADJUSTMENT",
                created_at=now,
                record_zero=True,
            )
            case.points_delta = old_points_delta + actual_delta

        restriction = await self.session.scalar(
            select(ReservationBookingRestriction)
            .where(ReservationBookingRestriction.penalty_case_id == case.id)
            .with_for_update()
        )
        if result == "REVOKE" or target_block_days <= 0:
            case.reservation_block_days = 0
            if restriction is not None and restriction.released_at is None:
                restriction.released_at = now
                restriction.release_reason = f"申诉复核{result_reason.strip()}"[:500]
        else:
            case.reservation_block_days = target_block_days
            end_at = case.applied_at + timedelta(days=target_block_days)
            if restriction is None:
                restriction = ReservationBookingRestriction(
                    user_id=case.user_id,
                    college_id=case.college_id,
                    scope_type="LAB",
                    scope_id=case.lab_id or 0,
                    reason=f"处罚 #{case.id} 的预约暂停",
                    penalty_case_id=case.id,
                    starts_at=case.applied_at,
                    ends_at=end_at,
                )
                self.session.add(restriction)
            else:
                restriction.ends_at = end_at
                restriction.released_at = now if end_at <= now else None
                restriction.release_reason = "复核后的预约暂停期限已结束" if end_at <= now else None
            if target_block_days > old_block_days and end_at > now:
                await _cancel_other_reservations(
                    self.session,
                    penalty=case,
                    event_at=now,
                )

        appeal.status = "REVIEWED"
        appeal.reviewer_id = self.principal.user_id
        appeal.result = result
        appeal.result_reason = result_reason.strip()
        appeal.adjusted_points_delta = case.points_delta
        appeal.adjusted_block_days = case.reservation_block_days
        appeal.reviewed_at = now
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=case.college_id,
            action="PENALTY_APPEAL_REVIEW",
            target_type="PENALTY_APPEAL",
            target_id=appeal.id,
            detail={
                "penalty_case_id": case.id,
                "attempt_number": appeal.attempt_number,
                "result": result,
                "reason": appeal.result_reason,
                "before": {
                    "points_delta": old_points_delta,
                    "block_days": old_block_days,
                },
                "after": {
                    "points_delta": case.points_delta,
                    "block_days": case.reservation_block_days,
                },
            },
        )
        review_label = {
            "MAINTAIN": "维持处罚",
            "ADJUST": "调整处罚",
            "REVOKE": "撤销处罚",
        }[result]
        enqueue_notification(
            self.session,
            task_key=f"notification:penalty-appeal:{appeal.id}:result:user:{case.user_id}",
            user_id=case.user_id,
            college_id=case.college_id,
            title="处罚申诉已有处理结果",
            content=(
                f"处罚 #{case.id} 的申诉已{review_label}。"
                f"处理理由：{appeal.result_reason}。"
                f"当前扣分 {-case.points_delta} 分，预约暂停 {case.reservation_block_days} 天。"
            ),
            related_id=appeal.id,
            related_type="PENALTY_APPEAL",
        )
        await self.session.commit()
        return self._appeal_data(appeal)

    async def list_overdue(self, page: int, page_size: int) -> dict[str, Any]:
        college_id = await self._college()
        await self._require_college_admin(college_id)
        page_offset(page, page_size)
        is_head = await self._is_college_head(college_id)
        base = select(ReservationOverdue.id).where(
            ReservationOverdue.college_id == college_id,
            ReservationOverdue.resolved_at.is_(None),
        )
        if not is_head:
            lab_scope = select(Lab.id).where(
                Lab.college_id == college_id,
                Lab.manager_id == self.principal.user_id,
            )
            base = base.where(ReservationOverdue.lab_id.in_(lab_scope))
        total = int(
            await self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        )
        page_ids = delayed_page_ids(
            base,
            ReservationOverdue.id,
            page=page,
            page_size=page_size,
            name="reservation_overdue_page_ids",
        )
        rows = list(
            (
                await self.session.execute(
                    select(
                        ReservationOverdue,
                        Reservation.id,
                        User.real_name,
                        User.username,
                        Device.name,
                        Lab.name,
                    )
                    .join(Reservation, Reservation.id == ReservationOverdue.reservation_id)
                    .join(User, User.id == ReservationOverdue.user_id)
                    .join(Device, Device.id == ReservationOverdue.device_id)
                    .outerjoin(Lab, Lab.id == ReservationOverdue.lab_id)
                    .join(page_ids, page_ids.c.id == ReservationOverdue.id)
                    .order_by(ReservationOverdue.started_at.asc(), ReservationOverdue.id.asc())
                )
            ).all()
        )
        items: list[dict[str, Any]] = []
        for overdue, reservation_id, real_name, username, device_name, lab_name in rows:
            followups = list(
                (
                    await self.session.execute(
                        select(ReservationOverdueFollowUp, User.real_name, User.username)
                        .join(User, User.id == ReservationOverdueFollowUp.operator_id)
                        .where(ReservationOverdueFollowUp.overdue_id == overdue.id)
                        .order_by(ReservationOverdueFollowUp.contacted_at.desc())
                        .limit(20)
                    )
                ).all()
            )
            items.append(
                {
                    "id": overdue.id,
                    "reservation_id": reservation_id,
                    "user_id": overdue.user_id,
                    "user_name": real_name or username,
                    "device_id": overdue.device_id,
                    "device_name": device_name,
                    "lab_id": overdue.lab_id,
                    "lab_name": lab_name,
                    "started_at": overdue.started_at,
                    "grace_deadline_at": overdue.grace_deadline_at,
                    "status": overdue.status,
                    "escalated_at": overdue.escalated_at,
                    "escalation_reason": overdue.escalation_reason,
                    "followups": [
                        {
                            "id": row.id,
                            "operator_name": operator_name or operator_username,
                            "contacted_at": row.contacted_at,
                            "result": row.result,
                        }
                        for row, operator_name, operator_username in followups
                    ],
                }
            )
        pages, truncated = page_metadata(total, page_size)
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "truncated": truncated,
        }

    async def add_followup(
        self,
        overdue_id: int,
        *,
        result: str,
        contacted_at: datetime | None,
    ) -> dict[str, Any]:
        if not result.strip():
            raise ApiError("OVERDUE_FOLLOWUP_REQUIRED", "请填写联系结果", 422)
        overdue = await self.session.scalar(
            select(ReservationOverdue).where(ReservationOverdue.id == overdue_id).with_for_update()
        )
        if overdue is None or overdue.resolved_at is not None:
            raise ApiError("OVERDUE_NOT_FOUND", "逾期跟进记录不存在或已结案", 404)
        await self._require_college_admin(overdue.college_id)
        is_head = await self._is_college_head(overdue.college_id)
        if not is_head:
            if overdue.lab_id is None:
                raise ApiError("FORBIDDEN", "只能跟进自己负责实验室的逾期案件", 403)
            owns_lab = await self.session.scalar(
                select(Lab.id).where(
                    Lab.id == overdue.lab_id,
                    Lab.college_id == overdue.college_id,
                    Lab.manager_id == self.principal.user_id,
                )
            )
            if owns_lab is None:
                raise ApiError("FORBIDDEN", "只能跟进自己负责实验室的逾期案件", 403)
        now = utcnow_naive()
        contact_time = contacted_at or now
        if contact_time.tzinfo is not None:
            contact_time = contact_time.astimezone(UTC).replace(tzinfo=None)
        if contact_time > now:
            raise ApiError("OVERDUE_CONTACT_TIME_INVALID", "联系时间不能晚于当前时间", 422)
        entry = ReservationOverdueFollowUp(
            overdue_id=overdue.id,
            operator_id=self.principal.user_id,
            contacted_at=contact_time,
            result=result.strip(),
            created_at=now,
        )
        self.session.add(entry)
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=overdue.college_id,
            action="RESERVATION_OVERDUE_FOLLOWUP",
            target_type="RESERVATION_OVERDUE",
            target_id=overdue.id,
            detail={"contacted_at": entry.contacted_at.isoformat(), "result": entry.result},
        )
        await self.session.commit()
        return {
            "id": entry.id,
            "overdue_id": entry.overdue_id,
            "contacted_at": entry.contacted_at,
            "result": entry.result,
        }

    async def escalate_overdue(self, overdue_id: int, *, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ApiError("OVERDUE_ESCALATION_REASON_REQUIRED", "请填写升级原因", 422)
        overdue = await self.session.scalar(
            select(ReservationOverdue).where(ReservationOverdue.id == overdue_id).with_for_update()
        )
        if overdue is None or overdue.resolved_at is not None:
            raise ApiError("OVERDUE_NOT_FOUND", "逾期案件不存在或已结案", 404)
        await self._require_college_admin(overdue.college_id)
        is_head = await self._is_college_head(overdue.college_id)
        if not is_head:
            if overdue.lab_id is None:
                raise ApiError("FORBIDDEN", "只能升级自己负责实验室的逾期案件", 403)
            owns_lab = await self.session.scalar(
                select(Lab.id).where(
                    Lab.id == overdue.lab_id,
                    Lab.college_id == overdue.college_id,
                    Lab.manager_id == self.principal.user_id,
                )
            )
            if owns_lab is None:
                raise ApiError("FORBIDDEN", "只能升级自己负责实验室的逾期案件", 403)
        followup_count = int(
            await self.session.scalar(
                select(func.count(ReservationOverdueFollowUp.id)).where(
                    ReservationOverdueFollowUp.overdue_id == overdue.id
                )
            )
            or 0
        )
        if followup_count < 1:
            raise ApiError("OVERDUE_FOLLOWUP_REQUIRED", "请先记录至少一次联系跟进", 409)
        if overdue.escalated_at is not None:
            raise ApiError("OVERDUE_ALREADY_ESCALATED", "该逾期案件已升级", 409)
        await self.session.scalar(select(User).where(User.id == overdue.user_id).with_for_update())
        now = utcnow_naive()
        overdue.escalated_at = now
        overdue.escalated_by = self.principal.user_id
        overdue.escalation_reason = reason.strip()
        overdue.status = "ESCALATED"
        overdue.updated_at = now
        restriction = ReservationBookingRestriction(
            user_id=overdue.user_id,
            college_id=overdue.college_id,
            scope_type="COLLEGE",
            scope_id=overdue.college_id,
            reason=f"逾期案件 #{overdue.id} 已升级至学院负责人",
            overdue_id=overdue.id,
            starts_at=now,
            ends_at=None,
        )
        self.session.add(restriction)
        append_audit(
            self.session,
            user_id=self.principal.user_id,
            college_id=overdue.college_id,
            action="RESERVATION_OVERDUE_ESCALATE",
            target_type="RESERVATION_OVERDUE",
            target_id=overdue.id,
            detail={"reason": reason.strip(), "scope": "COLLEGE"},
        )
        manager_id = await self.session.scalar(
            select(College.manager_id).where(College.id == overdue.college_id)
        )
        if manager_id is not None:
            enqueue_notification(
                self.session,
                task_key=f"notification:overdue:{overdue.id}:escalated:head:{manager_id}",
                user_id=int(manager_id),
                college_id=overdue.college_id,
                title="设备逾期案件已升级",
                content=(
                    f"逾期案件 #{overdue.id} 已升级至学院负责人。"
                    f"原因：{reason.strip()}。用户的新预约和新领用已暂停。"
                ),
                related_id=overdue.id,
                related_type="OVERDUE",
                notification_type="RESERVATION_OVERDUE",
            )
        enqueue_notification(
            self.session,
            task_key=f"notification:overdue:{overdue.id}:escalated:user:{overdue.user_id}",
            user_id=overdue.user_id,
            college_id=overdue.college_id,
            title="新预约和新领用已暂停",
            content="由于设备逾期未还且案件已升级至学院负责人，你在本学院的新预约和新领用暂时暂停。请通过通知中心联系管理员；报修和申诉仍可使用。",
            related_id=overdue.id,
            related_type="OVERDUE",
            notification_type="RESERVATION_OVERDUE",
        )
        await self.session.commit()
        return {"id": overdue.id, "status": overdue.status, "escalated_at": overdue.escalated_at}
