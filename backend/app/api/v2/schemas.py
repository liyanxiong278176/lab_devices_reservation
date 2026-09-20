from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DateWindow(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_order(self) -> "DateWindow":
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self

    def dates(self) -> list[date]:
        return [
            date.fromordinal(value)
            for value in range(self.start_date.toordinal(), self.end_date.toordinal() + 1)
        ]


class ReservationPlanRequest(BaseModel):
    device_id: int = Field(gt=0)
    purpose: str = Field(min_length=2, max_length=500)
    start_date: date | None = None
    end_date: date | None = None
    dates: list[date] | None = None
    windows: list[DateWindow] | None = None
    commit_mode: Literal["all_or_nothing", "available_only"] = "all_or_nothing"

    @model_validator(mode="after")
    def validate_shape(self) -> "ReservationPlanRequest":
        has_range = self.start_date is not None or self.end_date is not None
        has_dates = bool(self.dates)
        has_windows = bool(self.windows)
        if sum((has_range, has_dates, has_windows)) != 1:
            raise ValueError("请提供一个连续日期区间、日期列表或重复日期区间")
        if has_range and (self.start_date is None or self.end_date is None):
            raise ValueError("开始日期和结束日期必须同时提供")
        if has_range and self.end_date < self.start_date:  # type: ignore[operator]
            raise ValueError("结束日期不能早于开始日期")
        if self.dates:
            if len(set(self.dates)) != len(self.dates):
                raise ValueError("日期列表不能重复")
            self.dates = sorted(self.dates)
        return self

    def windows_for_request(self) -> list[DateWindow]:
        if self.start_date is not None and self.end_date is not None:
            return [DateWindow(start_date=self.start_date, end_date=self.end_date)]
        if self.dates:
            return [DateWindow(start_date=item, end_date=item) for item in self.dates]
        return list(self.windows or [])

    def requested_dates(self) -> list[date]:
        values: list[date] = []
        for window in self.windows_for_request():
            values.extend(window.dates())
        return sorted(set(values))


class ReservationConflict(BaseModel):
    date: date
    reason: str
    reservation_id: int | None = None
    status: str | None = None


class DeviceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    brand: str | None = None
    model: str | None = None
    specs: str | None = None
    image_url: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    lab_id: int | None = None
    lab_name: str | None = None
    college_id: int | None = None
    college_name: str | None = None
    need_approval: bool
    max_reservation_days: int
    tags: list[str] | None = None


class DeviceDetail(DeviceSummary):
    description: str | None = None
    location: str | None = None


class RecommendationData(BaseModel):
    device_id: int
    name: str
    category_id: int | None = None
    category_name: str | None = None
    lab_id: int | None = None
    lab_name: str | None = None
    score: float
    reason: str
    brand: str | None = None
    model: str | None = None
    status: str


class AvailabilityDay(BaseModel):
    date: date
    available: bool
    reservation_id: int | None = None
    status: str | None = None


class ReservationData(BaseModel):
    id: int
    device_id: int
    device_name: str
    user_id: int
    username: str | None = None
    real_name: str | None = None
    purpose: str | None
    start_date: date
    end_date: date
    dates: list[date]
    status: str
    batch_id: str | None = None
    need_approval: bool
    created_at: datetime | None = None


class ReservationPreflightData(BaseModel):
    device: DeviceSummary
    requested_dates: list[date]
    available_dates: list[date]
    conflicts: list[ReservationConflict]
    all_available: bool


class ReservationCreateData(BaseModel):
    created: list[ReservationData]
    skipped_conflicts: list[ReservationConflict]
    batch_id: str | None = None


class ReservationPage(BaseModel):
    items: list[ReservationData]
    total: int
    page: int
    page_size: int
    next_cursor: int | None = None
    has_more: bool = False


class TransitionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ApprovalRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RepairData(BaseModel):
    id: int
    device_id: int
    device_name: str
    college_id: int | None = None
    reporter_id: int
    reporter_name: str | None = None
    title: str
    description: str | None = None
    image_urls: list[str] | None = None
    status: str
    handler_id: int | None = None
    resolution_note: str | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None


class RepairPage(BaseModel):
    items: list[RepairData]
    total: int
    page: int
    page_size: int
    next_cursor: int | None = None
    has_more: bool = False
