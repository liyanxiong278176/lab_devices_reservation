"""Idempotent non-AI operational metadata seeded for real devices."""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.settings import Settings
from app.infrastructure.db.models import (
    Device,
    DeviceDocument,
    DeviceHandover,
    Reservation,
    Role,
    UploadAsset,
    User,
)


def _document_body(device: Device, *, safety: bool) -> str:
    name = device.name.strip()
    model = device.model or "未填写"
    lab = device.lab.name if device.lab is not None else "未分配实验室"
    asset_code = device.asset_code or f"LAB-{device.id:06d}"
    if safety:
        return f"""# {name} 安全须知

## 设备信息

- 资产编号：{asset_code}
- 设备名称：{name}
- 型号：{model}
- 所属实验室：{lab}

## 使用前确认

1. 预约人须使用本人账号，确认设备状态为“可用”，并完成必要的安全确认。
2. 检查电源、接地、外壳、连接线和防护部件；发现异常时立即停止使用并提交报修。
3. 不得拆卸、改装、旁路安全保护装置，不得将无关人员带入操作区域。

## 使用中要求

1. 按实验室负责人发布的操作规程执行，严禁超出设备适用范围。
2. 设备运行期间不得离开现场；出现异响、异味、过热或报警时立即停机并联系负责人。
3. 易燃、腐蚀、有毒或高温样品必须按照实验室安全规定单独评估。

## 结束后

1. 按操作规程完成停机、清洁、断电和耗材复位。
2. 归还前如实填写设备状态；发现损坏或缺件必须在归还备注中说明。
3. 发生人身或设备安全事件时，先采取紧急处置并立即通知实验室负责人。

> 本文档是系统为设备建立的基础安全须知，具体实验项目以学院和实验室最新安全制度为准。
"""
    return f"""# {name} 使用 SOP

## 适用范围

本 SOP 适用于资产编号 **{asset_code}**、型号 **{model}** 的设备，所在实验室为 **{lab}**。

## 1. 使用前

1. 在系统中完成预约；需要审批的设备必须等待负责人批准。
2. 阅读本设备最新安全须知和操作规程，确认设备处于可用状态。
3. 预约首日与负责人现场核对设备、配件并完成交接后，方可开始使用；异常情况先报修。

## 2. 标准操作

1. 按设备面板和实验室现场标识顺序开机，等待自检完成。
2. 按实验方案设置参数，首次使用或更换样品前先进行空载/空白检查。
3. 操作过程中持续观察运行状态，不得擅自修改系统保护参数。

## 3. 结束操作

1. 保存实验数据，按相反顺序停机并完成清洁。
2. 关闭电源和辅助设备，整理线缆、样品与配件。
3. 归还时在系统提交归还申请，由负责人现场验收后完成本次预约；若设备异常，填写故障现象和复现步骤。

## 4. 责任边界

未经过培训或未获得负责人授权的人员不得独立操作受控设备。实验室负责人可根据现场制度补充更严格的要求。
"""


async def _write_document(path: Path, content: str) -> None:
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")


async def backfill_unfinished_handovers(
    session: AsyncSession,
    now: datetime,
) -> None:
    """Ensure every unfinished reservation participates in the handover flow.

    Reservations already in use when the rule changed are marked as legacy
    in-use without inventing a handover operator or timestamp. Their actual
    return still enters the normal manager acceptance flow.
    """
    reservations = list(
        (
            await session.scalars(
                select(Reservation).where(Reservation.status.in_(("PENDING", "APPROVED", "IN_USE")))
            )
        ).all()
    )
    for reservation in reservations:
        handover = await session.scalar(
            select(DeviceHandover).where(DeviceHandover.reservation_id == reservation.id)
        )
        if reservation.status in {"PENDING", "APPROVED"}:
            status = (
                "EXCEPTION"
                if reservation.handover_status == "EXCEPTION"
                or (handover is not None and handover.status == "EXCEPTION")
                else "PENDING"
            )
        elif reservation.handover_status == "RETURN_PENDING" or (
            handover is not None and handover.status == "RETURN_PENDING"
        ):
            status = "RETURN_PENDING"
        elif (
            handover is not None
            and handover.status == "HANDED_OVER"
            and handover.handover_by is not None
            and handover.handover_at is not None
        ):
            status = "HANDED_OVER"
        else:
            status = "LEGACY_IN_USE"

        legacy_note = None
        if status == "LEGACY_IN_USE":
            legacy_note = "统一交接规则启用前已进入使用中；原流程未记录交接人和交接时间。"

        if handover is None:
            handover = DeviceHandover(
                reservation_id=reservation.id,
                device_id=reservation.device_id,
                user_id=reservation.user_id,
                college_id=reservation.college_id,
                status=status,
                handover_note=legacy_note,
                created_at=reservation.created_at or now,
                updated_at=now,
            )
            session.add(handover)
        else:
            handover.status = status
            handover.updated_at = now
            if legacy_note and not handover.handover_note:
                handover.handover_note = legacy_note
        reservation.handover_status = status


async def ensure_operational_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Backfill identities and publish one SOP plus one safety note per device.

    This is deliberately limited to non-AI operational data. It is safe to run
    on every startup: existing active documents are never duplicated, and
    device asset/QR identities are only filled when missing.
    """

    async with session_factory() as session:
        now = datetime.now(UTC).replace(tzinfo=None)
        await backfill_unfinished_handovers(session, now)
        admin = await session.scalar(
            select(User)
            .join(User.roles)
            .where(User.status == 1, Role.role_code == "SYS_ADMIN")
            .order_by(User.id)
        )
        if admin is None:
            await session.commit()
            return
        devices = list(
            (
                await session.scalars(
                    select(Device)
                    .options(selectinload(Device.lab))
                    .where(Device.status != "DELETED")
                    .order_by(Device.id)
                )
            ).all()
        )
        root = Path(settings.upload_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        for device in devices:
            if not device.asset_code:
                device.asset_code = f"LAB-{device.id:06d}"
            # Keep a representative controlled instrument in the seed data so
            # the qualification gate can be demonstrated without affecting
            # ordinary equipment. The rule is model-based, not ID-based.
            if (device.model or "").strip().upper() == "F79300":
                device.risk_level = "CRITICAL"
                device.requires_safety_ack = True
                device.requires_qualification = True
                device.allow_external_loan = True
            existing_types = set(
                (
                    await session.scalars(
                        select(DeviceDocument.document_type).where(
                            DeviceDocument.device_id == device.id,
                            DeviceDocument.active.is_(True),
                        )
                    )
                ).all()
            )
            for document_type, safety in (("SOP", False), ("SAFETY", True)):
                if document_type in existing_types:
                    continue
                token = secrets.token_urlsafe(32)
                suffix = ".md"
                path = root / f"{token}{suffix}"
                await _write_document(path, _document_body(device, safety=safety))
                asset = UploadAsset(
                    asset_token=token,
                    user_id=admin.id,
                    college_id=device.college_id,
                    original_name=f"{device.asset_code}-{document_type.lower()}.md",
                    content_type="text/markdown",
                    size_bytes=path.stat().st_size,
                    storage_path=str(path),
                    created_at=now,
                )
                document = DeviceDocument(
                    device_id=device.id,
                    college_id=device.college_id,
                    document_type=document_type,
                    title=(f"{device.name} 安全须知" if safety else f"{device.name} 使用 SOP"),
                    version="1.0",
                    requires_ack=safety and device.requires_safety_ack,
                    active=True,
                    created_by=admin.id,
                    created_at=now,
                    published_at=now,
                    asset=asset,
                )
                session.add(document)
        await session.commit()
