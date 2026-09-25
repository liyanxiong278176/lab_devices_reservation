from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_RESERVATION_PLAN_DAYS = 31


class DateWindow(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_order(self) -> "DateWindow":
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        if (self.end_date - self.start_date).days + 1 > MAX_RESERVATION_PLAN_DAYS:
            raise ValueError("单次预约最多支持 31 个自然日")
        return self

    def dates(self) -> list[date]:
        if (self.end_date - self.start_date).days + 1 > MAX_RESERVATION_PLAN_DAYS:
            raise ValueError("单次预约最多支持 31 个自然日")
        return [
            date.fromordinal(value)
            for value in range(self.start_date.toordinal(), self.end_date.toordinal() + 1)
        ]


class ReservationPlanRequest(BaseModel):
    device_id: int = Field(gt=0)
    purpose: str = Field(min_length=2, max_length=500)
    purpose_category: Literal["TEACHING", "RESEARCH", "COMPETITION_GRADUATION", "OTHER"] = "OTHER"
    project_reference: str | None = Field(default=None, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    dates: list[date] | None = Field(default=None, max_length=MAX_RESERVATION_PLAN_DAYS)
    windows: list[DateWindow] | None = Field(default=None, max_length=MAX_RESERVATION_PLAN_DAYS)
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
        if self.start_date is not None and self.end_date is not None:
            requested_days = (self.end_date - self.start_date).days + 1
            if requested_days > MAX_RESERVATION_PLAN_DAYS:
                raise ValueError("单次预约最多支持 31 个自然日")
        elif self.windows:
            requested_days = sum(
                (window.end_date - window.start_date).days + 1 for window in self.windows
            )
            if requested_days > MAX_RESERVATION_PLAN_DAYS:
                raise ValueError("单次预约最多支持 31 个自然日")
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
    accessory_checklist: list[str] = Field(default_factory=list)
    asset_code: str | None = None
    serial_number: str | None = None
    purchase_date: date | None = None
    warranty_until: date | None = None
    allow_external_loan: bool = False
    risk_level: str = "STANDARD"
    requires_safety_ack: bool = False
    requires_qualification: bool = False
    max_advance_days: int | None = None


class DeviceDetail(DeviceSummary):
    description: str | None = None
    location: str | None = None


class DeviceDocumentData(BaseModel):
    id: int
    device_id: int
    document_type: Literal["MANUAL", "SOP", "SAFETY"]
    title: str
    version: str = "1.0"
    requires_ack: bool = False
    original_name: str
    content_type: str
    size_bytes: int
    url: str
    created_by: int
    created_at: datetime | None = None
    published_at: datetime | None = None


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
    purpose_category: Literal["TEACHING", "RESEARCH", "COMPETITION_GRADUATION", "OTHER"] = "OTHER"
    project_reference: str | None = None
    start_date: date
    end_date: date
    dates: list[date]
    status: str
    batch_id: str | None = None
    need_approval: bool
    created_at: datetime | None = None
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    reject_reason: str | None = None
    inspection_condition: str | None = None
    inspection_note: str | None = None
    device_asset_code: str | None = None
    device_lab_name: str | None = None
    requires_handover: bool = False
    handover_status: str = "NOT_REQUIRED"
    safety_required: bool = False
    safety_acknowledged: bool = False
    safety_document_version: str | None = None
    handover_image_urls: list[str] = Field(default_factory=list)
    return_image_urls: list[str] = Field(default_factory=list)
    accessory_snapshot: list[str] = Field(default_factory=list)
    handover_checklist: list[dict[str, object]] = Field(default_factory=list)
    return_checklist: list[dict[str, object]] = Field(default_factory=list)
    fault_repair_id: int | None = None


class ReservationDateSuggestion(BaseModel):
    start_date: date
    end_date: date


class ReservationDeviceSuggestion(BaseModel):
    device_id: int
    name: str
    lab_name: str | None = None
    category_name: str | None = None


class ReservationPreflightData(BaseModel):
    device: DeviceSummary
    requested_dates: list[date]
    available_dates: list[date]
    conflicts: list[ReservationConflict]
    all_available: bool
    safety_required: bool = False
    safety_acknowledged: bool = False
    qualification_required: bool = False
    qualification_approved: bool = False
    safety_document_version: str | None = None
    qualification_valid_until: date | None = None
    same_device_suggestions: list[ReservationDateSuggestion] = Field(default_factory=list)
    similar_device_suggestions: list[ReservationDeviceSuggestion] = Field(default_factory=list)


class ReservationCreateData(BaseModel):
    created: list[ReservationData]
    skipped_conflicts: list[ReservationConflict]
    batch_id: str | None = None


class ReservationPage(BaseModel):
    items: list[ReservationData]
    total: int
    page: int
    page_size: int
    pages: int = 0
    truncated: bool = False


class FeedbackCreateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


class FeedbackData(BaseModel):
    id: int
    reservation_id: int
    device_id: int
    user_id: int
    rating: int
    comment: str | None = None
    created_at: datetime | None = None


class TransitionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReturnInspectionRequest(BaseModel):
    condition: Literal["NORMAL", "DAMAGED", "MISSING"] = "NORMAL"
    note: str | None = Field(default=None, max_length=1000)
    image_urls: list[str] = Field(min_length=1, max_length=6)


class AccessoryCheckInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    condition: Literal["NORMAL", "DAMAGED", "MISSING"]
    note: str | None = Field(default=None, max_length=300)


class HandoverRequest(BaseModel):
    condition: Literal["NORMAL", "DAMAGED", "MISSING"] = "NORMAL"
    note: str | None = Field(default=None, max_length=1000)
    image_urls: list[str] = Field(min_length=1, max_length=6)
    checklist: list[AccessoryCheckInput] = Field(default_factory=list, max_length=30)


class ReturnAcceptanceRequest(BaseModel):
    condition: Literal["NORMAL", "DAMAGED", "MISSING"] = "NORMAL"
    note: str | None = Field(default=None, max_length=1000)
    checklist: list[AccessoryCheckInput] = Field(default_factory=list, max_length=30)


class SafetyAcknowledgementRequest(BaseModel):
    reservation_id: int | None = Field(default=None, gt=0)


class QualificationSubmitRequest(BaseModel):
    qualification_type: str = Field(default="TRAINING", min_length=2, max_length=80)
    asset_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)


class QualificationReviewRequest(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    valid_until: date | None = None
    note: str | None = Field(default=None, max_length=500)


class RepairWorklogCreateRequest(BaseModel):
    content: str = Field(min_length=2, max_length=2000)
    image_urls: list[str] | None = Field(default=None, max_length=8)


class RepairConfirmationRequest(BaseModel):
    confirmed: bool
    note: str | None = Field(default=None, max_length=500)


class WaitlistCreateRequest(BaseModel):
    device_id: int = Field(gt=0)
    reservation_date: date
    purpose: str = Field(min_length=2, max_length=500)
    purpose_category: Literal["TEACHING", "RESEARCH", "COMPETITION_GRADUATION", "OTHER"] = "OTHER"
    project_reference: str | None = Field(default=None, max_length=160)


class WaitlistData(BaseModel):
    id: int
    device_id: int
    device_name: str | None = None
    reservation_date: date
    purpose: str
    purpose_category: Literal["TEACHING", "RESEARCH", "COMPETITION_GRADUATION", "OTHER"] = "OTHER"
    project_reference: str | None = None
    status: str
    created_at: datetime | None = None
    offered_until: datetime | None = None


class WaitlistConfirmationData(BaseModel):
    waitlist_id: int
    reservation: ReservationData


class BlackoutCreateRequest(BaseModel):
    scope_type: Literal["COLLEGE", "LAB", "DEVICE"]
    scope_id: int = Field(gt=0)
    blocked_date: date
    reason: str = Field(min_length=2, max_length=500)


class BlackoutData(BaseModel):
    id: int
    scope_type: str
    scope_id: int
    blocked_date: date
    reason: str
    active: bool
    created_at: datetime | None = None


class ApprovalRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RepairData(BaseModel):
    id: int
    device_id: int
    reservation_id: int | None = None
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
    priority: str = "NORMAL"
    response_due_at: datetime | None = None
    resolve_due_at: datetime | None = None
    user_confirmed_at: datetime | None = None
    user_confirmation_note: str | None = None
    closed_at: datetime | None = None


class RepairWorklogData(BaseModel):
    id: int
    report_id: int
    operator_id: int
    status: str
    content: str
    image_urls: list[str] | None = None
    created_at: datetime | None = None


class HandoverData(BaseModel):
    id: int
    reservation_id: int
    device_id: int
    user_id: int
    status: str
    handover_by: int | None = None
    handover_at: datetime | None = None
    handover_condition: str | None = None
    handover_note: str | None = None
    returned_by: int | None = None
    returned_at: datetime | None = None
    return_condition: str | None = None
    return_note: str | None = None


class QualificationData(BaseModel):
    id: int
    device_id: int
    user_id: int
    status: str
    qualification_type: str
    asset_id: int | None = None
    valid_until: date | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class QualificationUploadData(BaseModel):
    asset_id: int
    url: str
    name: str
    content_type: str
    size_bytes: int


class ExportTaskData(BaseModel):
    id: int
    export_type: str
    status: str
    row_count: int = 0
    download_url: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class RepairPage(BaseModel):
    items: list[RepairData]
    total: int
    page: int
    page_size: int
    pages: int = 0
    truncated: bool = False
