from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.reservation import ACTIVE_RESERVATION_STATUSES
from app.infrastructure.cache.redis import get_redis_circuit
from app.infrastructure.cache.reservation_quota import ReservationQuotaCache
from app.infrastructure.db.models import (
    Device,
    Reservation,
    ReservationItem,
    ReservationWaitlistOffer,
)

_logger = logging.getLogger(__name__)
_BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
_UNAVAILABLE_DEVICE_STATUSES = ("DELETED", "MAINTENANCE", "DISABLED", "RETIRED", "OFFLINE")


async def reconcile_reservation_quotas(
    session: AsyncSession,
    quota_cache: ReservationQuotaCache,
    *,
    start_date: date,
    days: int,
) -> None:
    """Refresh future pool/day hashes from current per-device MySQL occupancy."""
    if days < 1:
        return
    end_date = start_date + timedelta(days=days - 1)
    pool_id = func.coalesce(Device.pool_id, Device.id)

    devices = (
        await session.execute(
            select(Device.id, pool_id, Device.status).where(Device.status != "DELETED")
        )
    ).all()
    if not devices:
        return

    occupied_rows = (
        await session.execute(
            select(
                ReservationItem.device_id,
                ReservationItem.reservation_date,
            )
            .join(Reservation, Reservation.id == ReservationItem.reservation_id)
            .where(
                ReservationItem.reservation_date.between(start_date, end_date),
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
        )
    ).all()
    occupied = {(int(row[0]), row[1]) for row in occupied_rows}

    now = datetime.now(UTC).replace(tzinfo=None)
    waitlist_rows = (
        await session.execute(
            select(
                ReservationWaitlistOffer.device_id,
                ReservationWaitlistOffer.reservation_date,
            )
            .where(
                ReservationWaitlistOffer.reservation_date.between(start_date, end_date),
                ReservationWaitlistOffer.expires_at > now,
            )
        )
    ).all()
    waitlist_holds = {(int(row[0]), row[1]) for row in waitlist_rows}

    days_to_write = [start_date + timedelta(days=offset) for offset in range(days)]
    availability_by_pool: dict[int, dict[date, dict[int, bool]]] = {}
    for raw_device_id, raw_pool_id, status in devices:
        device_id = int(raw_device_id)
        current_pool_id = int(raw_pool_id)
        by_date = availability_by_pool.setdefault(
            current_pool_id,
            {current_day: {} for current_day in days_to_write},
        )
        for current_day in days_to_write:
            available = (
                status not in _UNAVAILABLE_DEVICE_STATUSES
                and (device_id, current_day) not in occupied
                and (device_id, current_day) not in waitlist_holds
            )
            by_date[current_day][device_id] = available

    for current_pool_id, availability_by_date in availability_by_pool.items():
        await quota_cache.reconcile(current_pool_id, availability_by_date)


async def reservation_quota_reconciliation_loop(app: object) -> None:
    """Periodically rebuild Redis quota hints; MySQL remains the safety gate."""
    state = getattr(app, "state")
    settings = state.settings
    session_factory: async_sessionmaker[AsyncSession] = state.session_factory
    quota_cache = ReservationQuotaCache(
        state.redis_client,
        get_redis_circuit(app),
    )
    interval = max(10, int(settings.reservation_quota_reconcile_interval_seconds))
    horizon = (
        max(settings.reservation_advance_days, settings.reservation_manager_advance_days)
        + settings.reservation_max_days
        + 2
    )
    while True:
        try:
            business_today = datetime.now(UTC).astimezone(_BUSINESS_TZ).date()
            async with session_factory() as session:
                await reconcile_reservation_quotas(
                    session,
                    quota_cache,
                    start_date=business_today,
                    days=horizon,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("Reservation quota reconciliation failed")
        await asyncio.sleep(interval)
