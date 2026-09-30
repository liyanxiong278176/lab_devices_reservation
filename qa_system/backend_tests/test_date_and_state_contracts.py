from __future__ import annotations

from datetime import date

import pytest
from app.api.v2.schemas import DateWindow, ReservationPlanRequest
from app.domain.reservation import RESERVATION_TRANSITIONS
from app.infrastructure.db.models import ReservationItem
from pydantic import ValidationError


def test_same_day_window_is_inclusive() -> None:
    window = DateWindow(start_date=date(2028, 2, 29), end_date=date(2028, 2, 29))
    assert window.dates() == [date(2028, 2, 29)]


def test_year_boundary_window_is_inclusive() -> None:
    request = ReservationPlanRequest(
        device_id=10,
        purpose="year boundary check",
        start_date=date(2028, 12, 31),
        end_date=date(2029, 1, 1),
    )
    assert request.requested_dates() == [date(2028, 12, 31), date(2029, 1, 1)]


@pytest.mark.parametrize(
    "dates",
    [
        {"start_date": date(2028, 3, 2), "end_date": date(2028, 3, 1)},
        {"start_date": date(2028, 1, 1), "end_date": date(2028, 2, 1)},
        {"dates": [date(2028, 3, 1), date(2028, 3, 1)]},
    ],
)
def test_invalid_date_range_and_duplicate_dates_are_rejected(dates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ReservationPlanRequest(device_id=10, purpose="range validation", **dates)


def test_reservation_state_machine_has_only_expected_edges() -> None:
    assert RESERVATION_TRANSITIONS == {
        "PENDING": ("APPROVED", "CANCELLED"),
        "APPROVED": ("IN_USE", "CANCELLED", "NO_SHOW", "VIOLATED"),
        "IN_USE": ("COMPLETED", "VIOLATED"),
        "COMPLETED": (),
        "CANCELLED": (),
        "REJECTED": (),
        "NO_SHOW": (),
        "VIOLATED": (),
    }


def test_database_unique_key_is_device_and_natural_date() -> None:
    unique_constraints = {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in ReservationItem.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("uk_device_date_v2", ("device_id", "date")) in unique_constraints
    assert "slot_index" not in {
        column.name for column in ReservationItem.__table__.primary_key.columns
    }
