from __future__ import annotations

import re
from datetime import date
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.policy import TOOL_POLICIES
from app.application.recommendations import RecommendationService
from app.application.reservations import ReservationService
from app.auth.security import Principal

_GENERIC_DEVICE_QUERY_TERMS = (
    "当前学院",
    "本学院",
    "有哪些",
    "有什么",
    "哪一些",
    "请问",
    "帮我",
    "我想要",
    "我想",
    "我需要",
    "找一下",
    "找",
    "查找",
    "查询",
    "搜索",
    "列出",
    "看看",
    "空闲的",
    "可用的",
    "空闲",
    "可用",
    "设备",
    "仪器",
    "列表",
    "实验室",
    "一台",
    "一个",
    "吗",
    "呢",
    "？",
    "?",
    "，",
    ",",
    "。",
)


def _normalize_device_query(query: str) -> str:
    """Turn conversational search text into a useful name/model fragment."""

    normalized = str(query or "").strip()
    for term in _GENERIC_DEVICE_QUERY_TERMS:
        normalized = normalized.replace(term, " ")
    return re.sub(r"\s+", " ", normalized).strip()[:100]


class SearchDevicesInput(BaseModel):
    query: str = Field(default="", max_length=100)


class RecommendDevicesInput(BaseModel):
    query: str = Field(default="", max_length=100)


class AvailabilityInput(BaseModel):
    device_id: int = Field(gt=0)
    start_date: date
    end_date: date


class CreateReservationInput(BaseModel):
    device_id: int = Field(gt=0)
    start_date: date
    end_date: date
    purpose: str = Field(min_length=2, max_length=500)


class CancelReservationInput(BaseModel):
    reservation_id: int = Field(gt=0)


class SubmitRepairInput(BaseModel):
    device_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


def build_tool_catalog(
    session: AsyncSession,
    principal: Principal,
    *,
    max_days: int,
) -> list[StructuredTool]:
    service = ReservationService(session, principal, max_days=max_days)
    recommendation_service = RecommendationService(session, principal)

    async def search_devices(query: str = "") -> dict[str, Any]:
        search = _normalize_device_query(query)
        items, total = await service.list_devices(search=search or None, page=1, page_size=20)
        return {"items": [item.model_dump(mode="json") for item in items], "total": total}

    async def recommend_devices(query: str = "") -> dict[str, Any]:
        del query  # The ranking uses persisted usage signals, not an untrusted filter.
        items = await recommendation_service.recommend(limit=10)
        return {"items": [item.model_dump(mode="json") for item in items], "total": len(items)}

    async def check_availability(
        device_id: int,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        days = await service.availability(device_id, start_date, end_date)
        return {"days": [day.model_dump(mode="json") for day in days]}

    async def my_reservations() -> dict[str, Any]:
        page = await service.list_mine(page=1, page_size=20)
        return page.model_dump(mode="json")

    async def create_reservation(
        device_id: int,
        start_date: date,
        end_date: date,
        purpose: str,
    ) -> dict[str, Any]:
        from app.api.v2.schemas import ReservationPlanRequest

        preflight = await service.preflight(
            ReservationPlanRequest(
                device_id=device_id,
                start_date=start_date,
                end_date=end_date,
                purpose=purpose,
            )
        )
        return {"confirmation_required": True, "preview": preflight.model_dump(mode="json")}

    async def cancel_reservation(reservation_id: int) -> dict[str, Any]:
        reservation = await service.get_reservation(reservation_id)
        return {"confirmation_required": True, "preview": reservation.model_dump(mode="json")}

    async def submit_repair(
        device_id: int,
        title: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        device = await service._load_device(device_id)
        return {
            "confirmation_required": True,
            "preview": {
                "device_id": device.id,
                "device_name": device.name,
                "title": title.strip(),
                "description": description.strip() if description else None,
                "next_status": "MAINTENANCE",
            },
        }

    tools = [
        StructuredTool.from_function(
            coroutine=search_devices,
            name="search_devices",
            description=TOOL_POLICIES["search_devices"].description,
            args_schema=SearchDevicesInput,
        ),
        StructuredTool.from_function(
            coroutine=recommend_devices,
            name="recommend_devices",
            description=TOOL_POLICIES["recommend_devices"].description,
            args_schema=RecommendDevicesInput,
        ),
        StructuredTool.from_function(
            coroutine=check_availability,
            name="check_availability",
            description=TOOL_POLICIES["check_availability"].description,
            args_schema=AvailabilityInput,
        ),
        StructuredTool.from_function(
            coroutine=my_reservations,
            name="my_reservations",
            description=TOOL_POLICIES["my_reservations"].description,
        ),
        StructuredTool.from_function(
            coroutine=create_reservation,
            name="create_reservation",
            description=TOOL_POLICIES["create_reservation"].description,
            args_schema=CreateReservationInput,
        ),
        StructuredTool.from_function(
            coroutine=cancel_reservation,
            name="cancel_reservation",
            description=TOOL_POLICIES["cancel_reservation"].description,
            args_schema=CancelReservationInput,
        ),
        StructuredTool.from_function(
            coroutine=submit_repair,
            name="submit_repair",
            description=TOOL_POLICIES["submit_repair"].description,
            args_schema=SubmitRepairInput,
        ),
    ]
    return [tool for tool in tools if TOOL_POLICIES[tool.name].allowed(principal)]
