from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class AiConfigUpdateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=120)
    api_key: str | None = Field(default=None, min_length=8, max_length=1000)
    base_url: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    daily_quota: int = Field(default=0, ge=0, le=1_000_000)


class AiConfigData(BaseModel):
    scope: str
    provider: str | None
    model: str | None
    base_url: str | None
    configured: bool
    enabled: bool
    daily_quota: int


class KnowledgeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default="FAQ", min_length=1, max_length=40)
    college_id: int | None = Field(default=None, gt=0)
    body: str = Field(min_length=20, max_length=200_000)


class KnowledgeData(BaseModel):
    id: int
    title: str
    source_type: str
    college_id: int | None
    status: str
    version: int
    chunk_count: int = 0
    created_at: datetime | None = None
    published_at: datetime | None = None
