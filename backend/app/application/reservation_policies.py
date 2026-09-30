from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import Principal
from app.infrastructure.db.models import Device, ReservationRule


@dataclass(frozen=True)
class EffectiveReservationPolicy:
    user_category: str
    max_booking_days: int
    max_advance_days: int
    approval_required: bool


def user_category_for(principal: Principal) -> str:
    return "LAB_ADMIN" if principal.is_lab_admin else "STUDENT"


def _scope_pairs(device: Device) -> list[tuple[str, int]]:
    return [
        ("DEVICE", device.id),
        *([("LAB", device.lab_id)] if device.lab_id is not None else []),
        *([("COLLEGE", device.college_id)] if device.college_id is not None else []),
        ("GLOBAL", 0),
    ]


async def resolve_reservation_policy(
    session: AsyncSession,
    principal: Principal,
    device: Device,
    *,
    default_max_booking_days: int = 31,
    default_student_advance_days: int = 30,
    default_manager_advance_days: int = 90,
) -> EffectiveReservationPolicy:
    """Resolve identity-specific rules first, then generic rules by resource scope.

    A more general rule can never silently relax a matching identity-specific
    policy. Fields are resolved independently so partial rules inherit safely.
    """
    scopes = _scope_pairs(device)
    conditions = [
        and_(ReservationRule.scope_type == scope_type, ReservationRule.scope_id == scope_id)
        for scope_type, scope_id in scopes
    ]
    rows = list(
        (
            await session.scalars(
                select(ReservationRule).where(
                    or_(*conditions),
                    ReservationRule.user_category.in_(("ALL", user_category_for(principal))),
                )
            )
        ).all()
    )
    by_key = {(row.scope_type, row.scope_id, row.user_category): row for row in rows}
    category = user_category_for(principal)

    def resolve_for_category(field: str, candidate_category: str):
        for scope_type, scope_id in scopes:
            rule = by_key.get((scope_type, scope_id, candidate_category))
            value = getattr(rule, field, None) if rule is not None else None
            if value is not None:
                return value
        return None

    def resolve(field: str):
        for candidate_category in (category, "ALL"):
            value = resolve_for_category(field, candidate_category)
            if value is not None:
                return value
        return None

    configured_booking_days = resolve("max_booking_days")
    if configured_booking_days is None:
        # Device fields remain the compatibility fallback for fixtures and
        # databases whose rules table has not yet been populated.
        max_booking_days = min(default_max_booking_days, device.max_reservation_days)
    else:
        max_booking_days = min(default_max_booking_days, int(configured_booking_days))

    category_default_advance_days = (
        default_manager_advance_days if principal.is_lab_admin else default_student_advance_days
    )
    category_advance_days = resolve_for_category("max_advance_days", category)
    if category_advance_days is not None:
        # Explicit identity rules are authoritative and may intentionally
        # differ from the default (within the API's configured range).
        max_advance_days = int(category_advance_days)
    else:
        # Generic rules and the legacy device field may tighten a role's
        # default, but must not silently extend the ordinary-user horizon.
        generic_advance_days = resolve_for_category("max_advance_days", "ALL")
        configured_advance_days = generic_advance_days or device.max_advance_days
        max_advance_days = min(
            int(configured_advance_days or category_default_advance_days),
            category_default_advance_days,
        )

    configured_approval = resolve("approval_required")
    approval_required = (
        bool(device.need_approval) if configured_approval is None else bool(configured_approval)
    )
    return EffectiveReservationPolicy(
        user_category=category,
        max_booking_days=max_booking_days,
        max_advance_days=max_advance_days,
        approval_required=approval_required,
    )
