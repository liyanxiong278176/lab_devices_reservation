"""Shared non-AI lifecycle helpers.

These helpers deliberately keep state changes in application services rather
than controllers.  They also make status changes auditable without coupling
the reservation date model to an hourly slot model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import AuditLog, Device, DeviceStatusHistory


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def change_device_status(
    session: AsyncSession,
    device: Device,
    new_status: str,
    *,
    operator_id: int | None,
    reason: str | None = None,
) -> bool:
    """Change a device status once and append a lifecycle record."""

    if device.status == new_status:
        return False
    old_status = device.status
    device.status = new_status
    session.add(
        DeviceStatusHistory(
            device_id=device.id,
            college_id=device.college_id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            operator_id=operator_id,
            created_at=utcnow_naive(),
        )
    )
    return True


def append_audit(
    session: AsyncSession,
    *,
    user_id: int | None,
    college_id: int | None,
    action: str,
    target_type: str,
    target_id: int | None,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            user_id=user_id,
            college_id=college_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            created_at=utcnow_naive(),
        )
    )
