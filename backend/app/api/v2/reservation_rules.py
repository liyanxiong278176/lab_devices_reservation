from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.lifecycle import append_audit
from app.application.scope_access import can_manage_scope, manageable_scope_condition
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import College, Device, Lab, ReservationRule
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class ReservationRuleWrite(BaseModel):
    scope_type: Literal["GLOBAL", "COLLEGE", "LAB", "DEVICE"]
    scope_id: int = Field(ge=0)
    user_category: Literal["ALL", "STUDENT", "LAB_ADMIN"]
    max_booking_days: int | None = Field(default=None, ge=1, le=31)
    max_advance_days: int | None = Field(default=None, ge=1, le=365)
    approval_required: bool | None = None

    @model_validator(mode="after")
    def validate_rule(self) -> ReservationRuleWrite:
        if self.scope_type == "GLOBAL" and self.scope_id != 0:
            raise ValueError("全校规则的范围编号必须为 0")
        if self.scope_type != "GLOBAL" and self.scope_id <= 0:
            raise ValueError("请选择有效的学院、实验室或设备")
        if (
            self.max_booking_days is None
            and self.max_advance_days is None
            and self.approval_required is None
        ):
            raise ValueError("至少配置一项预约限制")
        return self


class ReservationRuleData(BaseModel):
    id: int
    scope_type: str
    scope_id: int
    scope_name: str
    user_category: str
    max_booking_days: int | None
    max_advance_days: int | None
    approval_required: bool | None


class ReservationRulePage(BaseModel):
    items: list[ReservationRuleData]
    total: int
    page: int
    page_size: int
    pages: int
    truncated: bool = False


def _require_manager(principal: Principal) -> None:
    if not principal.has_permission("reservation-rule:manage"):
        raise ApiError("FORBIDDEN", "只有实验室负责人或系统管理员可以管理预约规则", 403)


def _data(rule: ReservationRule, scope_name: str) -> ReservationRuleData:
    return ReservationRuleData(
        id=rule.id,
        scope_type=rule.scope_type,
        scope_id=rule.scope_id,
        scope_name=scope_name,
        user_category=rule.user_category,
        max_booking_days=rule.max_booking_days,
        max_advance_days=rule.max_advance_days,
        approval_required=rule.approval_required,
    )


@router.get("/reservation-rules", response_model=ApiResponse[ReservationRulePage])
async def list_reservation_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    scope_type: Literal["GLOBAL", "COLLEGE", "LAB", "DEVICE"] | None = Query(default=None),
    user_category: Literal["ALL", "STUDENT", "LAB_ADMIN"] | None = Query(default=None),
    scope_id: int | None = Query(default=None, ge=0),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationRulePage]:
    _require_manager(principal)
    page_offset(page, page_size)
    scope_condition = manageable_scope_condition(principal)
    id_query = select(ReservationRule.id)
    count_query = select(func.count(ReservationRule.id))
    filters = []
    if scope_type is not None:
        filters.append(ReservationRule.scope_type == scope_type)
    if user_category is not None:
        filters.append(ReservationRule.user_category == user_category)
    if scope_id is not None:
        filters.append(ReservationRule.scope_id == scope_id)
    if filters:
        id_query = id_query.where(*filters)
        count_query = count_query.where(*filters)
    if scope_condition is not None:
        id_query = id_query.where(scope_condition)
        count_query = count_query.where(scope_condition)
    total = int(await session.scalar(count_query) or 0)
    page_ids = delayed_page_ids(
        id_query,
        ReservationRule.id,
        page=page,
        page_size=page_size,
        name="reservation_rule_page_ids",
    )
    rules = list(
        (
            await session.scalars(
                select(ReservationRule)
                .join(page_ids, page_ids.c.id == ReservationRule.id)
                .order_by(ReservationRule.id.desc())
            )
        ).all()
    )
    college_ids = {row.scope_id for row in rules if row.scope_type == "COLLEGE"}
    lab_ids = {row.scope_id for row in rules if row.scope_type == "LAB"}
    device_ids = {row.scope_id for row in rules if row.scope_type == "DEVICE"}
    college_names = (
        {
            row.id: row.name
            for row in (
                await session.scalars(select(College).where(College.id.in_(college_ids)))
            ).all()
        }
        if college_ids
        else {}
    )
    lab_names = (
        {
            row.id: row.name
            for row in (await session.scalars(select(Lab).where(Lab.id.in_(lab_ids)))).all()
        }
        if lab_ids
        else {}
    )
    device_names = (
        {
            row.id: row.name
            for row in (
                await session.scalars(select(Device).where(Device.id.in_(device_ids)))
            ).all()
        }
        if device_ids
        else {}
    )
    names = {"COLLEGE": college_names, "LAB": lab_names, "DEVICE": device_names}
    pages, truncated = page_metadata(total, page_size)
    return ApiResponse.ok(
        ReservationRulePage(
            items=[
            _data(
                rule,
                "全校默认"
                if rule.scope_type == "GLOBAL"
                else names[rule.scope_type].get(rule.scope_id, f"#{rule.scope_id}"),
            )
            for rule in rules
            ],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            truncated=truncated,
        )
    )


@router.put("/reservation-rules", response_model=ApiResponse[ReservationRuleData])
async def upsert_reservation_rule(
    payload: ReservationRuleWrite,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationRuleData]:
    _require_manager(principal)
    if payload.scope_type == "GLOBAL" and not principal.is_system_admin:
        raise ApiError("FORBIDDEN", "全校默认规则仅系统管理员可以修改", 403)
    if not await can_manage_scope(session, principal, payload.scope_type, payload.scope_id):
        raise ApiError("FORBIDDEN", "只能管理自己负责范围内的预约规则", 403)

    statement = (
        select(ReservationRule)
        .where(
            ReservationRule.scope_type == payload.scope_type,
            ReservationRule.scope_id == payload.scope_id,
            ReservationRule.user_category == payload.user_category,
        )
        .with_for_update()
    )
    rule = await session.scalar(statement)
    values = payload.model_dump()
    if rule is not None:
        for field in ("max_booking_days", "max_advance_days", "approval_required"):
            setattr(rule, field, values[field])
        rule.updated_by = principal.user_id
    else:
        rule = ReservationRule(
            **values,
            created_by=principal.user_id,
            updated_by=principal.user_id,
        )
        session.add(rule)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            "RULE_CONFLICT", "该范围和用户类别的规则已被同时创建，请刷新后重试", 409
        ) from exc

    scope_name = "全校默认"
    if payload.scope_type == "COLLEGE":
        scope_name = str(
            await session.scalar(select(College.name).where(College.id == payload.scope_id))
            or f"#{payload.scope_id}"
        )
    elif payload.scope_type == "LAB":
        scope_name = str(
            await session.scalar(select(Lab.name).where(Lab.id == payload.scope_id))
            or f"#{payload.scope_id}"
        )
    elif payload.scope_type == "DEVICE":
        scope_name = str(
            await session.scalar(select(Device.name).where(Device.id == payload.scope_id))
            or f"#{payload.scope_id}"
        )
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=principal.college_id,
        action="RESERVATION_RULE_UPSERT",
        target_type="RESERVATION_RULE",
        target_id=rule.id,
        detail=values,
    )
    await session.commit()
    return ApiResponse.ok(_data(rule, scope_name))


@router.delete("/reservation-rules/{rule_id}", response_model=ApiResponse[None])
async def delete_reservation_rule(
    rule_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    _require_manager(principal)
    rule = await session.scalar(
        select(ReservationRule).where(ReservationRule.id == rule_id).with_for_update()
    )
    if rule is None or not await can_manage_scope(
        session, principal, rule.scope_type, rule.scope_id
    ):
        raise ApiError("RULE_NOT_FOUND", "规则不存在或无权操作", 404)
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=principal.college_id,
        action="RESERVATION_RULE_DELETE",
        target_type="RESERVATION_RULE",
        target_id=rule.id,
        detail={
            "scope_type": rule.scope_type,
            "scope_id": rule.scope_id,
            "user_category": rule.user_category,
        },
    )
    await session.delete(rule)
    await session.commit()
    return ApiResponse.ok(None)
