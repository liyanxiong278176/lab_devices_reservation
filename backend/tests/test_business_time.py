from __future__ import annotations

from datetime import date, datetime

from app.core.business_time import (
    business_date_at_utc_naive,
    business_day_end_utc_naive,
    business_day_start_utc_naive,
)


def test_shanghai_day_boundaries_are_stored_as_utc_naive() -> None:
    day = date(2026, 10, 5)

    assert business_day_start_utc_naive(day) == datetime(2026, 10, 4, 16)
    assert business_day_end_utc_naive(day) == datetime(2026, 10, 5, 15, 59, 59, 999999)
    assert business_date_at_utc_naive(business_day_start_utc_naive(day)) == day
    assert business_date_at_utc_naive(business_day_end_utc_naive(day)) == day
