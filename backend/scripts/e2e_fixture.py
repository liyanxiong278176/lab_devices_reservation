"""Create and remove isolated data for the browser-level regression suite.

The fixture never touches the seeded demo users or the three real colleges. A
unique ``e2e-`` prefix makes accidental cleanup outside the test tenant
impossible to miss in review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.security import hash_password
from app.core.settings import Settings
from app.infrastructure.db.models import (
    AiAuxUsageEvent,
    AiCheckpoint,
    AiCheckpointWrite,
    AiConfirmation,
    AiConversation,
    AiEmbeddingRebuildJob,
    AiMessage,
    AiRun,
    AiRunEvent,
    AiUsageEvent,
    AuditLog,
    College,
    CreditEvent,
    Device,
    DeviceCategory,
    DeviceDocument,
    DeviceHandover,
    DeviceMaintenancePlan,
    DeviceMaintenanceRecord,
    DeviceStatusHistory,
    ExportTask,
    IdempotencyKey,
    Lab,
    Notification,
    OutboxTask,
    RefreshSession,
    RepairReport,
    Reservation,
    ReservationBlackout,
    ReservationFeedback,
    ReservationInspection,
    ReservationItem,
    ReservationRule,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    Role,
    UploadAsset,
    User,
    user_roles,
)
from app.infrastructure.db.session import build_engine, build_session_factory
from app.infrastructure.notifications.sequence import next_delivery_sequence
from sqlalchemy import delete, or_, select


def validate_prefix(value: str) -> str:
    if not re.fullmatch(r"e2e-[a-z0-9-]{6,40}", value):
        raise ValueError("prefix must match e2e-[a-z0-9-]{6,40}")
    return value


async def seed(prefix: str) -> None:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    password = "E2e-123456"
    username = f"{prefix}-user"
    device_name = f"{prefix}-device"
    second_device_name = f"{prefix}-device-2"
    manager_username = f"{prefix}-manager"
    admin_username = f"{prefix}-admin"
    try:
        async with factory() as session:
            student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
            manager_role = await session.scalar(select(Role).where(Role.role_code == "LAB_ADMIN"))
            admin_role = await session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
            if student_role is None or manager_role is None or admin_role is None:
                raise RuntimeError("required STUDENT/LAB_ADMIN/SYS_ADMIN roles are missing")

            college = College(
                code=prefix.upper(),
                name=f"E2E 测试学院 {prefix}",
                status=1,
            )
            category = DeviceCategory(name=f"{prefix}-category", parent_id=0, sort=0)
            manager = User(
                username=manager_username,
                password_hash=hash_password(password),
                real_name="E2E 负责人",
                user_type="STAFF",
                status=1,
                roles=[manager_role],
            )
            admin = User(
                username=admin_username,
                password_hash=hash_password(password),
                real_name="E2E 系统管理员",
                user_type="STAFF",
                status=1,
                roles=[admin_role],
            )
            student = User(
                username=username,
                password_hash=hash_password(password),
                real_name="E2E 普通用户",
                user_type="STUDENT",
                status=1,
                roles=[student_role],
            )
            waitlist_user = User(
                username=f"{prefix}-user2",
                password_hash=hash_password(password),
                real_name="E2E 候补用户",
                user_type="STUDENT",
                status=1,
                roles=[student_role],
            )
            college.users.extend([manager, student, waitlist_user])
            lab = Lab(
                name=f"{prefix}-lab",
                location="E2E 测试楼",
                description="浏览器回归测试专用实验室",
                status=1,
                manager=manager,
            )
            college.labs.append(lab)
            device = Device(
                name=device_name,
                brand="E2E",
                model=device_name,
                specs="E2E regression fixture",
                status="IDLE",
                need_approval=True,
                max_reservation_days=8,
                accessory_checklist=["电源线"],
                description="浏览器回归测试专用设备",
                college=college,
                lab=lab,
                category=category,
            )
            second_device = Device(
                name=second_device_name,
                brand="E2E",
                model=second_device_name,
                specs="E2E regression fixture",
                status="IDLE",
                need_approval=True,
                max_reservation_days=8,
                accessory_checklist=["电源线"],
                description="浏览器回归测试备用设备",
                college=college,
                lab=lab,
                category=category,
            )
            session.add_all(
                [
                    college,
                    manager,
                    admin,
                    student,
                    waitlist_user,
                    lab,
                    category,
                    device,
                    second_device,
                ]
            )
            await session.flush()
            college.manager_id = manager.id
            await session.commit()
            print(
                json.dumps(
                    {
                        "prefix": prefix,
                        "username": username,
                        "password": password,
                        "alternate_username": f"{prefix}-user2",
                        "manager_username": manager_username,
                        "admin_username": admin_username,
                        "device_id": device.id,
                        "device_name": device_name,
                        "second_device_id": second_device.id,
                        "second_device_name": second_device.name,
                        "college_id": college.id,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        await engine.dispose()


async def add_notification(prefix: str, title: str) -> None:
    if not title or len(title) > 200:
        raise ValueError("notification title must contain 1 to 200 characters")
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            student = await session.scalar(
                select(User).where(User.username == f"{prefix}-user")
            )
            if student is None:
                raise RuntimeError("E2E student fixture does not exist")
            delivery_sequence = await next_delivery_sequence(session, student.id)
            session.add(
                Notification(
                    user_id=student.id,
                    college_id=student.college_id,
                    type="SYSTEM",
                    title=title,
                    content="此通知在 SSE 断线期间创建。",
                    delivery_sequence=delivery_sequence,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def cleanup(prefix: str) -> None:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            college = await session.scalar(select(College).where(College.code == prefix.upper()))
            if college is None:
                return
            users = list(
                (await session.scalars(select(User).where(User.username.like(f"{prefix}%")))).all()
            )
            user_ids = [user.id for user in users]
            device_ids = list(
                (
                    await session.scalars(select(Device.id).where(Device.college_id == college.id))
                ).all()
            )
            lab_ids = list(
                (await session.scalars(select(Lab.id).where(Lab.college_id == college.id))).all()
            )
            reservation_id_query = select(Reservation.id).where(
                Reservation.college_id == college.id
            )
            conversations = list(
                (
                    await session.execute(
                        select(AiConversation.id, AiConversation.graph_thread_id).where(
                            AiConversation.user_id.in_(user_ids or [-1])
                        )
                    )
                ).all()
            )
            conversation_ids = [conversation_id for conversation_id, _ in conversations]
            conversation_thread_ids = [thread_id for _, thread_id in conversations]
            ai_run_ids = list(
                (
                    await session.scalars(
                        select(AiRun.id).where(
                            or_(
                                AiRun.user_id.in_(user_ids or [-1]),
                                AiRun.conversation_id.in_(conversation_ids or [-1]),
                            )
                        )
                    )
                ).all()
            )
            export_scope = ExportTask.college_id == college.id
            if user_ids:
                export_scope = export_scope | ExportTask.requester_id.in_(user_ids)
            export_files = list(
                (
                    await session.execute(
                        select(ExportTask.id, ExportTask.file_path).where(export_scope)
                    )
                ).all()
            )
            document_assets = list(
                (
                    await session.execute(
                        select(UploadAsset.id, UploadAsset.storage_path)
                        .join(DeviceDocument, DeviceDocument.asset_id == UploadAsset.id)
                        .where(DeviceDocument.device_id.in_(device_ids or [-1]))
                    )
                ).all()
            )
            scope_ids = [college.id, *lab_ids, *device_ids]
            maintenance_assets = list(
                (
                    await session.execute(
                        select(UploadAsset.id, UploadAsset.storage_path)
                        .join(
                            DeviceMaintenanceRecord,
                            DeviceMaintenanceRecord.evidence_asset_id == UploadAsset.id,
                        )
                        .where(DeviceMaintenanceRecord.device_id.in_(device_ids or [-1]))
                    )
                ).all()
            )
            await session.execute(
                delete(ReservationRule).where(
                    or_(
                        (ReservationRule.scope_type == "COLLEGE")
                        & (ReservationRule.scope_id == college.id),
                        (ReservationRule.scope_type == "LAB")
                        & ReservationRule.scope_id.in_(lab_ids or [-1]),
                        (ReservationRule.scope_type == "DEVICE")
                        & ReservationRule.scope_id.in_(device_ids or [-1]),
                    )
                )
            )
            if user_ids:
                await session.execute(
                    delete(AiAuxUsageEvent).where(AiAuxUsageEvent.user_id.in_(user_ids))
                )
                await session.execute(
                    delete(AiEmbeddingRebuildJob).where(
                        AiEmbeddingRebuildJob.requested_by.in_(user_ids)
                    )
                )
                await session.execute(
                    delete(AiUsageEvent).where(AiUsageEvent.user_id.in_(user_ids))
                )
                await session.execute(
                    delete(AiConfirmation).where(AiConfirmation.user_id.in_(user_ids))
                )
                await session.execute(delete(AiMessage).where(AiMessage.user_id.in_(user_ids)))
            if conversation_thread_ids:
                await session.execute(
                    delete(AiCheckpointWrite).where(
                        AiCheckpointWrite.thread_id.in_(conversation_thread_ids)
                    )
                )
                await session.execute(
                    delete(AiCheckpoint).where(
                        AiCheckpoint.thread_id.in_(conversation_thread_ids)
                    )
                )
            if ai_run_ids:
                await session.execute(delete(AiRunEvent).where(AiRunEvent.run_id.in_(ai_run_ids)))
                await session.execute(
                    delete(AiUsageEvent).where(AiUsageEvent.run_id.in_(ai_run_ids))
                )
                await session.execute(
                    delete(AiConfirmation).where(AiConfirmation.run_id.in_(ai_run_ids))
                )
                await session.execute(delete(AiRun).where(AiRun.id.in_(ai_run_ids)))
            if conversation_ids:
                await session.execute(
                    delete(AiMessage).where(AiMessage.conversation_id.in_(conversation_ids))
                )
                await session.execute(
                    delete(AiConfirmation).where(
                        AiConfirmation.conversation_id.in_(conversation_ids)
                    )
                )
                await session.execute(
                    delete(AiConversation).where(AiConversation.id.in_(conversation_ids))
                )
            if user_ids:
                await session.execute(
                    delete(Notification).where(Notification.user_id.in_(user_ids))
                )
                await session.execute(
                    delete(ReservationBlackout).where(
                        (ReservationBlackout.created_by.in_(user_ids))
                        | (ReservationBlackout.scope_id.in_(scope_ids or [-1]))
                    )
                )
                await session.execute(delete(AuditLog).where(AuditLog.user_id.in_(user_ids)))
                await session.execute(
                    delete(RefreshSession).where(RefreshSession.user_id.in_(user_ids))
                )
            if device_ids:
                await session.execute(
                    delete(DeviceMaintenanceRecord).where(
                        DeviceMaintenanceRecord.device_id.in_(device_ids)
                    )
                )
                await session.execute(
                    delete(DeviceMaintenancePlan).where(
                        DeviceMaintenancePlan.device_id.in_(device_ids)
                    )
                )
                await session.execute(
                    delete(ReservationWaitlistOffer).where(
                        ReservationWaitlistOffer.device_id.in_(device_ids)
                    )
                )
                await session.execute(
                    delete(ReservationWaitlist).where(
                        ReservationWaitlist.device_id.in_(device_ids)
                    )
                )
                await session.execute(
                    delete(DeviceDocument).where(DeviceDocument.device_id.in_(device_ids))
                )
                await session.execute(
                    delete(DeviceStatusHistory).where(
                        DeviceStatusHistory.device_id.in_(device_ids)
                    )
                )
            await session.execute(
                delete(DeviceHandover).where(
                    DeviceHandover.reservation_id.in_(reservation_id_query)
                )
            )
            await session.execute(
                delete(ReservationFeedback).where(
                    ReservationFeedback.reservation_id.in_(reservation_id_query)
                )
            )
            await session.execute(
                delete(ReservationInspection).where(
                    ReservationInspection.reservation_id.in_(reservation_id_query)
                )
            )
            await session.execute(
                delete(CreditEvent).where(CreditEvent.reservation_id.in_(reservation_id_query))
            )
            await session.execute(
                delete(ReservationItem).where(
                    ReservationItem.reservation_id.in_(reservation_id_query)
                )
            )
            if device_ids:
                await session.execute(
                    delete(RepairReport).where(RepairReport.device_id.in_(device_ids))
                )
            await session.execute(delete(Reservation).where(Reservation.college_id == college.id))
            await session.execute(delete(Notification).where(Notification.college_id == college.id))
            await session.execute(delete(OutboxTask).where(OutboxTask.college_id == college.id))
            await session.execute(delete(ExportTask).where(export_scope))
            if user_ids:
                await session.execute(
                    delete(IdempotencyKey).where(IdempotencyKey.user_id.in_(user_ids))
                )
                await session.execute(delete(UploadAsset).where(UploadAsset.user_id.in_(user_ids)))
            if document_assets:
                await session.execute(
                    delete(UploadAsset).where(
                        UploadAsset.id.in_([asset_id for asset_id, _ in document_assets])
                    )
                )
            if maintenance_assets:
                await session.execute(
                    delete(UploadAsset).where(
                        UploadAsset.id.in_([asset_id for asset_id, _ in maintenance_assets])
                    )
                )
            await session.execute(delete(Device).where(Device.college_id == college.id))
            await session.execute(delete(Lab).where(Lab.college_id == college.id))
            if user_ids:
                await session.execute(
                    College.__table__.update()
                    .where(College.id == college.id)
                    .values(manager_id=None)
                )
                await session.execute(delete(user_roles).where(user_roles.c.user_id.in_(user_ids)))
                await session.execute(delete(User).where(User.id.in_(user_ids)))
            await session.execute(delete(College).where(College.id == college.id))
            await session.commit()
            for _, storage_path in document_assets:
                Path(storage_path).unlink(missing_ok=True)
            for _, storage_path in maintenance_assets:
                Path(storage_path).unlink(missing_ok=True)
            export_root = (Path(settings.upload_dir).resolve() / "exports").resolve()
            for _, storage_path in export_files:
                if storage_path:
                    export_path = Path(storage_path).resolve()
                    if export_path.parent == export_root:
                        export_path.unlink(missing_ok=True)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "notification", "cleanup"))
    parser.add_argument("--prefix", required=True, type=validate_prefix)
    parser.add_argument("--title")
    args = parser.parse_args()
    if args.action == "seed":
        asyncio.run(seed(args.prefix))
    elif args.action == "notification":
        asyncio.run(add_notification(args.prefix, args.title or ""))
    else:
        asyncio.run(cleanup(args.prefix))


if __name__ == "__main__":
    main()
