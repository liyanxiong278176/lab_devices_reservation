from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationData(BaseModel):
    id: int
    title: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChatRunData(BaseModel):
    run_id: int
    conversation_id: int
    status: str


class ConfirmationData(BaseModel):
    id: int
    run_id: int
    tool_name: str
    reason: str
    risk_summary: str
    estimated_impact: str
    preview: dict[str, object]
    status: Literal["PENDING", "CONFIRMED", "CANCELLED", "EXPIRED", "EXECUTED", "FAILED"]
    expires_at: datetime


class AiConfigData(BaseModel):
    component: str = "chat"
    scope: str = "environment"
    source: Literal["environment", "missing"] = "missing"
    provider: str | None
    model: str | None
    base_url: str | None
    configured: bool
    enabled: bool
    daily_quota: int
    user_daily_token_cap: int = 0
    college_daily_token_cap: int = 0
    global_daily_token_cap: int = 0
    last_tested_at: datetime | None = None


class AiConfigTestData(BaseModel):
    component: str
    success: bool
    message: str
    model: str
    latency_ms: int


class KnowledgeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default="FAQ", min_length=1, max_length=40)
    college_id: int | None = Field(default=None, gt=0)
    lab_id: int | None = Field(default=None, gt=0)
    device_id: int | None = Field(default=None, gt=0)
    allowed_roles: list[str] = Field(default_factory=list, max_length=20)
    body: str = Field(default="", max_length=200_000)


class KnowledgeBuildJobData(BaseModel):
    job_id: str
    task_id: str
    document_id: int
    version: int
    status: str
    stage: str
    progress_percent: int | None
    completed_units: int
    total_units: int | None
    unit: str | None
    attempts: int
    redeliveries: int = 0
    dispatch_recoveries: int = 0
    error_summary: str | None = None
    skipped_by: int | None = None
    skipped_at: datetime | None = None
    skip_reason: str | None = None
    blocking_job_id: str | None = None
    blocking_job_version: int | None = None
    blocking_job_status: str | None = None
    blocking_job_error_summary: str | None = None
    created_at: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class KnowledgeData(BaseModel):
    id: int
    title: str
    source_type: str
    college_id: int | None
    lab_id: int | None = None
    device_id: int | None = None
    allowed_roles: list[str] = Field(default_factory=list)
    status: str
    version: int
    chunk_count: int = 0
    created_at: datetime | None = None
    published_at: datetime | None = None
    source_file_name: str | None = None
    parse_status: str = "NOT_REQUESTED"
    parse_error: str | None = None
    dlp_categories: list[str] = Field(default_factory=list)
    build_job: KnowledgeBuildJobData | None = None


class KnowledgeBuildAcceptedData(BaseModel):
    document_id: int
    job_id: str
    task_id: str
    status: str
    build_job: KnowledgeBuildJobData


class KnowledgeRoleOption(BaseModel):
    code: str
    name: str


class KnowledgeReviewRequest(BaseModel):
    reviewed_text: str = Field(min_length=20, max_length=500_000)


class KnowledgeBuildSkipRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("skip reason must contain at least two non-space characters")
        return normalized


class AiDomainTermCreateRequest(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    canonical: str | None = Field(default=None, max_length=100)
    kind: Literal["SYNONYM", "IGNORE"] = "SYNONYM"
    college_id: int | None = Field(default=None, gt=0)


class AiDomainTermData(BaseModel):
    id: int
    college_id: int | None
    term: str
    canonical: str | None
    kind: Literal["SYNONYM", "IGNORE"]
    status: str


class AiEmbeddingRebuildRequest(BaseModel):
    """Rebuild using the active Embedding configuration loaded from the root .env."""


class AiEmbeddingRebuildData(BaseModel):
    id: int
    status: str
    source_collection: str
    target_collection: str
    model: str
    total_points: int
    indexed_points: int
    error_code: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
