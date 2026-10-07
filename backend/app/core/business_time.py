"""Business-date boundaries stored as UTC-naive database timestamps."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


def business_day_start_utc_naive(day: date) -> datetime:
    """Return the start of a Shanghai calendar day as a UTC-naive timestamp."""
    local_start = datetime.combine(day, time.min, tzinfo=BUSINESS_TIMEZONE)
    return local_start.astimezone(UTC).replace(tzinfo=None)


def business_day_end_utc_naive(day: date) -> datetime:
    """Return the final representable instant of a Shanghai calendar day in UTC."""
    return business_day_start_utc_naive(day + timedelta(days=1)) - timedelta(microseconds=1)


def business_date_at_utc_naive(value: datetime) -> date:
    """Convert a UTC-naive database timestamp to its Shanghai calendar date."""
    return value.replace(tzinfo=UTC).astimezone(BUSINESS_TIMEZONE).date()
