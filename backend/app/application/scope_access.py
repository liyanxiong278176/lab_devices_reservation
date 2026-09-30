from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import Principal, college_scope
from app.infrastructure.db.models import College, Device, Lab, ReservationRule


def manageable_device_ids_statement(principal: Principal):
    """Return a tenant- and manager-scoped device ID query for list filtering."""
    if principal.is_system_admin:
        return select(Device.id)
    college_id = college_scope(principal)
    if college_id is None or not principal.is_lab_admin:
        return select(Device.id).where(False)
    return (
        select(Device.id)
        .outerjoin(Lab, Lab.id == Device.lab_id)
        .join(College, College.id == Device.college_id)
        .where(
            Device.college_id == college_id,
            or_(Lab.manager_id == principal.user_id, College.manager_id == principal.user_id),
        )
    )


async def can_manage_scope(
    session: AsyncSession,
    principal: Principal,
    scope_type: str,
    scope_id: int,
) -> bool:
    if scope_type == "GLOBAL":
        return principal.is_system_admin and scope_id == 0
    if principal.is_system_admin:
        if scope_type == "COLLEGE":
            statement = select(College.id).where(College.id == scope_id)
        elif scope_type == "LAB":
            statement = select(Lab.id).where(Lab.id == scope_id)
        elif scope_type == "DEVICE":
            statement = select(Device.id).where(Device.id == scope_id)
        else:
            return False
        return bool(await session.scalar(statement))
    college_id = college_scope(principal)
    if college_id is None or not principal.is_lab_admin:
        return False
    if scope_type == "COLLEGE":
        return bool(
            await session.scalar(
                select(College.id).where(
                    College.id == scope_id,
                    College.id == college_id,
                    College.manager_id == principal.user_id,
                )
            )
        )
    if scope_type == "LAB":
        return bool(
            await session.scalar(
                select(Lab.id)
                .where(
                    Lab.id == scope_id,
                    Lab.college_id == college_id,
                    or_(
                        Lab.manager_id == principal.user_id,
                        College.manager_id == principal.user_id,
                    ),
                )
                .join(College, College.id == Lab.college_id)
            )
        )
    if scope_type == "DEVICE":
        return bool(
            await session.scalar(
                select(Device.id)
                .outerjoin(Lab, Lab.id == Device.lab_id)
                .join(College, College.id == Device.college_id)
                .where(
                    Device.id == scope_id,
                    Device.college_id == college_id,
                    or_(
                        Lab.manager_id == principal.user_id,
                        College.manager_id == principal.user_id,
                    ),
                )
            )
        )
    return False


def manageable_scope_condition(principal: Principal):
    """SQL predicate restricting a manager's rule list to their owned scopes."""
    if principal.is_system_admin:
        return None
    college_id = college_scope(principal)
    if college_id is None or not principal.is_lab_admin:
        return False
    managed_colleges = select(College.id).where(
        College.id == college_id,
        College.manager_id == principal.user_id,
    )
    managed_labs = (
        select(Lab.id)
        .join(College, College.id == Lab.college_id)
        .where(
            Lab.college_id == college_id,
            or_(Lab.manager_id == principal.user_id, College.manager_id == principal.user_id),
        )
    )
    managed_devices = manageable_device_ids_statement(principal)
    return or_(
        (ReservationRule.scope_type == "COLLEGE") & ReservationRule.scope_id.in_(managed_colleges),
        (ReservationRule.scope_type == "LAB") & ReservationRule.scope_id.in_(managed_labs),
        (ReservationRule.scope_type == "DEVICE") & ReservationRule.scope_id.in_(managed_devices),
    )
