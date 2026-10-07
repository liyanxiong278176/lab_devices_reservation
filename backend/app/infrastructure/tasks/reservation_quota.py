from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.reservation import ACTIVE_RESERVATION_STATUSES
from app.infrastructure.cache.redis import get_redis_circuit
from app.infrastructure.cache.reservation_quota import (
    ReservationQuotaCache,
    get_reservation_quota_readiness,
)
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
) -> bool:
    """Refresh future pool/day hashes from current per-device MySQL occupancy."""
    if days < 1:
        return True
    end_date = start_date + timedelta(days=days - 1)
    pool_id = func.coalesce(Device.pool_id, Device.id)

    devices = (
        await session.execute(
            select(Device.id, pool_id, Device.status).where(Device.status != "DELETED")
        )
    ).all()
    if not devices:
        return True

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

    complete = True
    for current_pool_id, availability_by_date in availability_by_pool.items():
        complete = await quota_cache.reconcile(
            current_pool_id,
            availability_by_date,
        ) and complete
    return complete


async def reconcile_reservation_quota_pool_dates(
    session: AsyncSession,
    quota_cache: ReservationQuotaCache,
    *,
    pool_id: int,
    dates: list[date],
) -> None:
    """Rebuild one pool's requested date hashes from a MySQL snapshot."""
    ordered_dates = sorted(set(dates))
    if not ordered_dates:
        return
    pool_expression = func.coalesce(Device.pool_id, Device.id)
    devices = (
        await session.execute(
            select(Device.id, Device.status).where(
                pool_expression == pool_id,
                Device.status != "DELETED",
            )
        )
    ).all()
    device_ids = [int(row[0]) for row in devices]
    if not device_ids:
        return

    occupied_rows = (
        await session.execute(
            select(ReservationItem.device_id, ReservationItem.reservation_date)
            .join(Reservation, Reservation.id == ReservationItem.reservation_id)
            .where(
                ReservationItem.device_id.in_(device_ids),
                ReservationItem.reservation_date.between(ordered_dates[0], ordered_dates[-1]),
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
            ).where(
                ReservationWaitlistOffer.device_id.in_(device_ids),
                ReservationWaitlistOffer.reservation_date.in_(ordered_dates),
                ReservationWaitlistOffer.expires_at > now,
            )
        )
    ).all()
    waitlist_holds = {(int(row[0]), row[1]) for row in waitlist_rows}
    availability = {
        current_day: {
            int(device_id): (
                status not in _UNAVAILABLE_DEVICE_STATUSES
                and (int(device_id), current_day) not in occupied
                and (int(device_id), current_day) not in waitlist_holds
            )
            for device_id, status in devices
        }
        for current_day in ordered_dates
    }
    await quota_cache.reconcile(
        pool_id,
        availability,
        raise_errors=True,
        track_mutation=True,
    )


async def reservation_quota_reconciliation_loop(app: object) -> None:
    """Periodically rebuild Redis quota hints; MySQL remains the safety gate."""
    state = getattr(app, "state")
    settings = state.settings
    session_factory: async_sessionmaker[AsyncSession] = state.session_factory
    quota_cache = ReservationQuotaCache(
        state.redis_client,
        get_redis_circuit(app),
        get_reservation_quota_readiness(app),
    )
    readiness = get_reservation_quota_readiness(app)
    interval = max(10, int(settings.reservation_quota_reconcile_interval_seconds))
    horizon = (
        max(settings.reservation_advance_days, settings.reservation_manager_advance_days)
        + settings.reservation_max_days
        + 2
    )
    while True:
        try:
            was_ready = readiness.ready
            rebuild_generation = readiness.generation
            business_today = datetime.now(UTC).astimezone(_BUSINESS_TZ).date()
            async with session_factory() as session:
                complete = await reconcile_reservation_quotas(
                    session,
                    quota_cache,
                    start_date=business_today,
                    days=horizon,
                )
            if complete and readiness.generation == rebuild_generation:
                readiness.ready = True
            elif was_ready:
                readiness.ready = False
        except asyncio.CancelledError:
            raise
        except Exception:
            readiness.ready = False
            _logger.exception("Reservation quota reconciliation failed")
        await asyncio.sleep(interval)
