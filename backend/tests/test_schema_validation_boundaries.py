from __future__ import annotations

from datetime import date

import pytest
from app.api.v2.schemas import (
    DateWindow,
    MaintenancePlanWrite,
    MaintenanceRecordCreate,
    ReservationPlanRequest,
)
from pydantic import ValidationError


def _reservation_plan(**values: object) -> ReservationPlanRequest:
    return ReservationPlanRequest(device_id=1, purpose="实验预约", **values)


def test_date_window_rejects_reverse_and_oversized_ranges() -> None:
    with pytest.raises(ValidationError, match="结束日期不能早于开始日期"):
        DateWindow(start_date=date(2026, 1, 2), end_date=date(2026, 1, 1))

    with pytest.raises(ValidationError, match="单次预约最多支持 31 个自然日"):
        DateWindow(start_date=date(2026, 1, 1), end_date=date(2026, 2, 1))

    # Exercise the defensive invariant for internally constructed models too.
    oversized = DateWindow.model_construct(start_date=date(2026, 1, 1), end_date=date(2026, 2, 1))
    with pytest.raises(ValueError, match="单次预约最多支持 31 个自然日"):
        oversized.dates()


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({}, "请提供一个连续日期区间"),
        ({"start_date": date(2026, 1, 1)}, "开始日期和结束日期必须同时提供"),
        (
            {
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 1),
                "dates": [date(2026, 1, 1)],
            },
            "请提供一个连续日期区间",
        ),
        (
            {"start_date": date(2026, 1, 2), "end_date": date(2026, 1, 1)},
            "结束日期不能早于开始日期",
        ),
        (
            {"dates": [date(2026, 1, 1), date(2026, 1, 1)]},
            "日期列表不能重复",
        ),
        (
            {"start_date": date(2026, 1, 1), "end_date": date(2026, 2, 1)},
            "单次预约最多支持 31 个自然日",
        ),
        (
            {
                "windows": [
                    {"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 3)},
                    {"start_date": date(2026, 1, 3), "end_date": date(2026, 1, 4)},
                ]
            },
            "重复日期区间不能重叠",
        ),
        (
            {
                "windows": [
                    {"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 16)},
                    {"start_date": date(2026, 1, 18), "end_date": date(2026, 2, 2)},
                ]
            },
            "单次预约最多支持 31 个自然日",
        ),
    ],
)
def test_reservation_plan_rejects_invalid_shapes(values: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _reservation_plan(**values)


def test_reservation_plan_requires_one_resource_target_and_valid_pool_preference() -> None:
    target = {"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 1), "purpose": "实验预约"}
    with pytest.raises(ValidationError, match="必须且只能指定一个设备或设备资源池"):
        ReservationPlanRequest(**target)
    with pytest.raises(ValidationError, match="必须且只能指定一个设备或设备资源池"):
        ReservationPlanRequest(device_id=1, pool_id=2, **target)
    with pytest.raises(ValidationError, match="指定预分配设备时必须同时指定设备资源池"):
        ReservationPlanRequest(device_id=1, preferred_device_id=3, **target)

    pool_plan = ReservationPlanRequest(pool_id=2, preferred_device_id=3, **target)
    assert pool_plan.pool_id == 2
    assert pool_plan.preferred_device_id == 3


def test_reservation_plan_normalizes_and_expands_each_supported_shape() -> None:
    first = date(2026, 1, 1)
    second = date(2026, 1, 2)
    third = date(2026, 1, 3)

    ranged = _reservation_plan(start_date=first, end_date=second)
    assert ranged.windows_for_request() == [DateWindow(start_date=first, end_date=second)]
    assert ranged.requested_dates() == [first, second]
    assert ranged.reservation_segments() == [[first, second]]

    explicit = _reservation_plan(dates=[third, first])
    assert explicit.dates == [first, third]
    assert explicit.windows_for_request() == [
        DateWindow(start_date=first, end_date=first),
        DateWindow(start_date=third, end_date=third),
    ]
    assert explicit.requested_dates() == [first, third]
    assert explicit.reservation_segments() == [[first], [third]]

    windows = _reservation_plan(
        windows=[
            {"start_date": third, "end_date": third},
            {"start_date": first, "end_date": second},
        ]
    )
    assert windows.windows_for_request() == [
        DateWindow(start_date=third, end_date=third),
        DateWindow(start_date=first, end_date=second),
    ]
    assert windows.requested_dates() == [first, second, third]
    assert windows.reservation_segments() == [[third], [first, second]]

    constructed_without_shape = ReservationPlanRequest.model_construct(
        device_id=1, purpose="内部构造", start_date=None, end_date=None, dates=None, windows=None
    )
    assert constructed_without_shape.windows_for_request() == []
    assert constructed_without_shape.reservation_segments() == []


def test_reservation_plan_accepts_non_overlapping_windows_in_any_input_order() -> None:
    first = date(2026, 1, 1)
    later = date(2026, 1, 4)
    plan = _reservation_plan(
        windows=[
            {"start_date": later, "end_date": later},
            {"start_date": first, "end_date": first},
        ]
    )
    assert plan.windows == [
        DateWindow(start_date=later, end_date=later),
        DateWindow(start_date=first, end_date=first),
    ]


def test_maintenance_write_validates_title_and_downtime_boundaries() -> None:
    base = {
        "plan_type": "ROUTINE",
        "title": "  日常检查  ",
        "interval_value": 1,
        "interval_unit": "DAY",
        "due_date": date(2026, 1, 2),
    }
    plan = MaintenancePlanWrite(**base)
    assert plan.title == "日常检查"
    assert MaintenancePlanWrite(**{**base, "downtime_start": None, "downtime_end": None})

    with pytest.raises(ValidationError, match="计划名称至少需要 2 个字符"):
        MaintenancePlanWrite(**{**base, "title": "  "})
    with pytest.raises(ValidationError, match="计划停机开始和结束日期必须同时填写"):
        MaintenancePlanWrite(**{**base, "downtime_start": date(2026, 1, 1)})
    with pytest.raises(ValidationError, match="计划停机结束日期不能早于开始日期"):
        MaintenancePlanWrite(
            **{
                **base,
                "downtime_start": date(2026, 1, 3),
                "downtime_end": date(2026, 1, 1),
            }
        )


def test_maintenance_record_normalizes_notes_and_requires_failure_details() -> None:
    base = {"cycle_due_date": date(2026, 1, 1), "completed_date": date(2026, 1, 2)}
    passed = MaintenanceRecordCreate(**base, result="PASSED", notes="  通过  ")
    assert passed.notes == "通过"
    assert MaintenanceRecordCreate(**base, result="PASSED", notes="   ").notes is None
    assert MaintenanceRecordCreate(**base, result="FAILED", notes="存在误差").notes == "存在误差"

    with pytest.raises(ValidationError, match="检查不合格时请填写不合格情况"):
        MaintenanceRecordCreate(**base, result="FAILED", notes="   ")
