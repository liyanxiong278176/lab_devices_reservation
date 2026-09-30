"""Create and remove isolated QA principals, tenants, labs, and devices.

This factory talks directly to the local MySQL schema through production ORM
models. It does not import or invoke any existing project test/e2e/benchmark
fixture. Generated passwords are disposable and only stored in the ignored
fixture manifest so locust and browser contexts can log in.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import uuid
from pathlib import Path

from pwdlib import PasswordHash
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.infrastructure.db import models  # noqa: E402
from config import FIXTURE_FILE, REDIS_URL, require_mysql_dsn  # noqa: E402

PASSWORD_HASH = PasswordHash.recommended()


def _fixture_path(value: str | None) -> Path:
    path = Path(value) if value else FIXTURE_FILE
    return path if path.is_absolute() else ROOT / path


async def create_fixture(path: Path) -> dict[str, object]:
    dsn = require_mysql_dsn()
    run_id = uuid.uuid4().hex[:10]
    password = f"QaEval-{secrets.token_urlsafe(15)}-A9!"
    engine = create_async_engine(dsn, pool_pre_ping=True, pool_size=5, max_overflow=5)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    try:
        async with factory() as session:
            role_rows = (
                await session.scalars(
                    select(models.Role).where(
                        models.Role.role_code.in_(["STUDENT", "LAB_ADMIN", "SYS_ADMIN"])
                    )
                )
            ).all()
            roles = {role.role_code: role for role in role_rows}
            missing = {"STUDENT", "LAB_ADMIN", "SYS_ADMIN"} - set(roles)
            if missing:
                raise RuntimeError(f"MySQL is missing required role fixtures: {sorted(missing)}")

            colleges: dict[str, models.College] = {}
            for slug, label in (("CSE", "计算机学院"), ("BIO", "生命学院")):
                colleges[slug] = models.College(
                    code=f"QAEVAL-{run_id}-{slug}",
                    name=f"QA隔离学院-{run_id}-{slug}",
                    status=1,
                )
            session.add_all(colleges.values())
            await session.flush()

            admin = models.User(
                username=f"qaeval-{run_id}-admin",
                password_hash=PASSWORD_HASH.hash(password),
                real_name="QA 系统管理员",
                user_type="STAFF",
                college_id=None,
                status=1,
                roles=[roles["SYS_ADMIN"]],
            )
            managers: dict[str, models.User] = {}
            students: dict[str, list[models.User]] = {"CSE": [], "BIO": []}
            for slug, college in colleges.items():
                manager = models.User(
                    username=f"qaeval-{run_id}-{slug.lower()}-manager",
                    password_hash=PASSWORD_HASH.hash(password),
                    real_name=f"QA {slug} 负责人",
                    user_type="STAFF",
                    college_id=college.id,
                    status=1,
                    roles=[roles["LAB_ADMIN"]],
                )
                managers[slug] = manager
                for index in range(1, 21):
                    students[slug].append(
                        models.User(
                            username=f"qaeval-{run_id}-{slug.lower()}-s{index:02d}",
                            password_hash=PASSWORD_HASH.hash(password),
                            real_name=f"QA {slug} 学生 {index:02d}",
                            user_type="STUDENT",
                            college_id=college.id,
                            status=1,
                            roles=[roles["STUDENT"]],
                        )
                    )
            sse_user = models.User(
                username=f"qaeval-{run_id}-sse",
                password_hash=PASSWORD_HASH.hash(password),
                real_name="QA SSE 专用学生",
                user_type="STUDENT",
                college_id=colleges["CSE"].id,
                status=1,
                roles=[roles["STUDENT"]],
            )
            performance_users = [
                models.User(
                    username=f"qaeval-{run_id}-perf-{index}",
                    password_hash=PASSWORD_HASH.hash(password),
                    real_name=f"QA 性能用户 {index}",
                    user_type="STUDENT",
                    college_id=colleges["CSE"].id,
                    status=1,
                    roles=[roles["STUDENT"]],
                )
                for index in (1, 2, 3)
            ]
            students["CSE"].extend([sse_user, *performance_users])
            session.add_all(
                [admin, *managers.values(), *(u for group in students.values() for u in group)]
            )
            await session.flush()

            labs: dict[str, models.Lab] = {}
            categories: dict[str, models.DeviceCategory] = {}
            for slug, college in colleges.items():
                college.manager_id = managers[slug].id
                labs[slug] = models.Lab(
                    college_id=college.id,
                    name=f"qa-lab-{run_id}-{slug.lower()}",
                    location="本地隔离测试楼",
                    manager_id=managers[slug].id,
                    description="qa_eval 临时数据，可安全清理",
                    status=1,
                )
                categories[slug] = models.DeviceCategory(
                    name=f"qa-category-{run_id}-{slug.lower()}", parent_id=0, sort=0
                )
            session.add_all([*labs.values(), *categories.values()])
            await session.flush()

            devices: dict[str, list[models.Device]] = {"CSE": [], "BIO": []}
            for slug, college in colleges.items():
                for index in range(1, 7):
                    devices[slug].append(
                        models.Device(
                            college_id=college.id,
                            lab_id=labs[slug].id,
                            category_id=categories[slug].id,
                            name=f"qa-device-{run_id}-{slug.lower()}-{index:02d}",
                            brand="QA",
                            model=f"QA-{slug}-{index:02d}",
                            specs="临时隔离评测设备",
                            status="IDLE",
                            need_approval=index % 2 == 1,
                            max_reservation_days=8,
                            description="qa_eval 临时数据",
                            accessory_checklist=[],
                        )
                    )
            session.add_all([device for group in devices.values() for device in group])
            await session.flush()
            await session.commit()

            manifest: dict[str, object] = {
                "run_id": run_id,
                "password": password,
                "college_ids": {key: value.id for key, value in colleges.items()},
                "manager_ids": {key: value.id for key, value in managers.items()},
                "student_ids": {
                    key: [user.id for user in values] for key, values in students.items()
                },
                "device_ids": {
                    key: [device.id for device in values] for key, values in devices.items()
                },
                "accounts": {
                    "admin": {"username": admin.username, "user_id": admin.id},
                    "sse": {"username": sse_user.username, "user_id": sse_user.id},
                    "perf": [
                        {"username": user.username, "user_id": user.id}
                        for user in performance_users
                    ],
                    "managers": {
                        key: {"username": value.username, "user_id": value.id}
                        for key, value in managers.items()
                    },
                    "students": {
                        key: [{"username": user.username, "user_id": user.id} for user in values]
                        for key, values in students.items()
                    },
                },
                "devices": {
                    key: [
                        {
                            "id": device.id,
                            "name": device.name,
                            "need_approval": device.need_approval,
                        }
                        for device in values
                    ]
                    for key, values in devices.items()
                },
                "lab_ids": {key: value.id for key, value in labs.items()},
                "category_ids": {key: value.id for key, value in categories.items()},
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
    finally:
        await engine.dispose()


async def cleanup_fixture(path: Path) -> None:
    """Delete only rows whose exact IDs appear in a factory-generated manifest."""

    if not path.exists():
        raise FileNotFoundError(f"Fixture manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or len(run_id) != 10 or not run_id.isalnum():
        raise ValueError("Refusing cleanup: fixture run_id is not factory-generated")

    college_ids = list(manifest["college_ids"].values())
    user_ids = [manifest["accounts"]["admin"]["user_id"]]
    user_ids.extend(manifest["manager_ids"].values())
    for users in manifest["student_ids"].values():
        user_ids.extend(users)
    device_ids = [value for group in manifest["device_ids"].values() for value in group]
    lab_ids = list(manifest["lab_ids"].values())
    category_ids = list(manifest["category_ids"].values())
    dsn = require_mysql_dsn()
    engine = create_async_engine(dsn, pool_pre_ping=True, pool_size=3, max_overflow=2)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    try:
        async with factory() as session:
            reservation_ids = select(models.Reservation.id).where(
                models.Reservation.user_id.in_(user_ids)
                | models.Reservation.device_id.in_(device_ids)
            )
            repair_ids = list(
                (
                    await session.scalars(
                        select(models.RepairReport.id).where(
                            models.RepairReport.reporter_id.in_(user_ids)
                            | models.RepairReport.device_id.in_(device_ids)
                            | models.RepairReport.reservation_id.in_(reservation_ids)
                        )
                    )
                ).all()
            )
            document_ids = list(
                (
                    await session.scalars(
                        select(models.DeviceDocument.id).where(
                            models.DeviceDocument.device_id.in_(device_ids)
                        )
                    )
                ).all()
            )
            asset_rows = list(
                (
                    await session.scalars(
                        select(models.UploadAsset).where(models.UploadAsset.user_id.in_(user_ids))
                    )
                ).all()
            )
            asset_paths = [asset.storage_path for asset in asset_rows]

            await session.execute(
                delete(models.DeviceHandover).where(
                    models.DeviceHandover.reservation_id.in_(reservation_ids)
                )
            )
            await session.execute(
                delete(models.ReservationInspection).where(
                    models.ReservationInspection.reservation_id.in_(reservation_ids)
                )
            )
            await session.execute(
                delete(models.ReservationFeedback).where(
                    models.ReservationFeedback.reservation_id.in_(reservation_ids)
                )
            )
            if repair_ids:
                await session.execute(
                    delete(models.RepairWorklog).where(
                        models.RepairWorklog.report_id.in_(repair_ids)
                    )
                )
                await session.execute(
                    delete(models.RepairReport).where(models.RepairReport.id.in_(repair_ids))
                )
            if document_ids:
                await session.execute(
                    delete(models.DeviceDocumentAcknowledgement).where(
                        models.DeviceDocumentAcknowledgement.document_id.in_(document_ids)
                    )
                )
                await session.execute(
                    delete(models.DeviceDocument).where(models.DeviceDocument.id.in_(document_ids))
                )

            await session.execute(
                delete(models.ReservationWaitlistOffer).where(
                    models.ReservationWaitlistOffer.user_id.in_(user_ids)
                    | models.ReservationWaitlistOffer.device_id.in_(device_ids)
                )
            )
            await session.execute(
                delete(models.ReservationWaitlist).where(
                    models.ReservationWaitlist.user_id.in_(user_ids)
                    | models.ReservationWaitlist.device_id.in_(device_ids)
                )
            )
            await session.execute(
                delete(models.ReservationItem).where(
                    models.ReservationItem.device_id.in_(device_ids)
                    | models.ReservationItem.reservation_id.in_(reservation_ids)
                )
            )
            await session.execute(
                delete(models.CreditEvent).where(
                    models.CreditEvent.user_id.in_(user_ids)
                    | models.CreditEvent.reservation_id.in_(reservation_ids)
                )
            )
            await session.execute(
                delete(models.OutboxTask).where(
                    models.OutboxTask.college_id.in_(college_ids)
                    | models.OutboxTask.aggregate_key.like(f"%{run_id}%")
                )
            )
            await session.execute(
                delete(models.Notification).where(models.Notification.user_id.in_(user_ids))
            )
            await session.execute(
                delete(models.IdempotencyKey).where(models.IdempotencyKey.user_id.in_(user_ids))
            )
            await session.execute(
                delete(models.RefreshSession).where(models.RefreshSession.user_id.in_(user_ids))
            )
            await session.execute(
                delete(models.DeviceQualification).where(
                    models.DeviceQualification.user_id.in_(user_ids)
                    | models.DeviceQualification.device_id.in_(device_ids)
                )
            )
            await session.execute(
                delete(models.UploadAsset).where(models.UploadAsset.user_id.in_(user_ids))
            )
            await session.execute(
                delete(models.UploadQuotaBucket).where(
                    (models.UploadQuotaBucket.scope_type == "USER")
                    & models.UploadQuotaBucket.scope_id.in_(user_ids)
                    | (models.UploadQuotaBucket.scope_type == "COLLEGE")
                    & models.UploadQuotaBucket.scope_id.in_(college_ids)
                )
            )
            await session.execute(
                delete(models.DeviceStatusHistory).where(
                    models.DeviceStatusHistory.device_id.in_(device_ids)
                )
            )
            await session.execute(
                delete(models.ReservationBlackout).where(
                    models.ReservationBlackout.scope_id.in_(college_ids + lab_ids + device_ids)
                )
            )
            await session.execute(
                delete(models.ReservationRule).where(
                    models.ReservationRule.scope_id.in_(college_ids + lab_ids + device_ids)
                )
            )
            await session.execute(
                delete(models.AuditLog).where(
                    models.AuditLog.user_id.in_(user_ids)
                    | models.AuditLog.college_id.in_(college_ids)
                )
            )
            await session.execute(
                delete(models.Reservation).where(
                    models.Reservation.user_id.in_(user_ids)
                    | models.Reservation.device_id.in_(device_ids)
                )
            )
            await session.execute(
                delete(models.DeviceMaintenanceRecord).where(
                    models.DeviceMaintenanceRecord.device_id.in_(device_ids)
                )
            )
            await session.execute(
                delete(models.DeviceMaintenancePlan).where(
                    models.DeviceMaintenancePlan.device_id.in_(device_ids)
                )
            )
            await session.execute(delete(models.Device).where(models.Device.id.in_(device_ids)))
            await session.execute(delete(models.Lab).where(models.Lab.id.in_(lab_ids)))
            await session.execute(
                models.College.__table__.update()
                .where(models.College.id.in_(college_ids))
                .values(manager_id=None)
            )
            await session.execute(delete(models.User).where(models.User.id.in_(user_ids)))
            await session.execute(
                delete(models.DeviceCategory).where(models.DeviceCategory.id.in_(category_ids))
            )
            await session.execute(delete(models.College).where(models.College.id.in_(college_ids)))
            await session.commit()
            remaining = {
                "users": int(
                    await session.scalar(
                        select(func.count(models.User.id)).where(models.User.id.in_(user_ids))
                    )
                    or 0
                ),
                "devices": int(
                    await session.scalar(
                        select(func.count(models.Device.id)).where(models.Device.id.in_(device_ids))
                    )
                    or 0
                ),
                "reservations": int(
                    await session.scalar(
                        select(func.count(models.Reservation.id)).where(
                            models.Reservation.user_id.in_(user_ids)
                            | models.Reservation.device_id.in_(device_ids)
                        )
                    )
                    or 0
                ),
                "notifications": int(
                    await session.scalar(
                        select(func.count(models.Notification.id)).where(
                            models.Notification.user_id.in_(user_ids)
                        )
                    )
                    or 0
                ),
                "outbox": int(
                    await session.scalar(
                        select(func.count(models.OutboxTask.id)).where(
                            models.OutboxTask.college_id.in_(college_ids)
                            | models.OutboxTask.aggregate_key.like(f"%{run_id}%")
                        )
                    )
                    or 0
                ),
                "colleges": int(
                    await session.scalar(
                        select(func.count(models.College.id)).where(
                            models.College.id.in_(college_ids)
                        )
                    )
                    or 0
                ),
            }
            if any(remaining.values()):
                raise RuntimeError(f"Exact-ID QA cleanup left rows behind: {remaining}")
        allowed_upload_roots = {
            (ROOT / "backend" / ".data" / "uploads").resolve(),
            (ROOT / ".data" / "uploads").resolve(),
        }
        for value in asset_paths:
            candidate = Path(value).resolve()
            if candidate.parent in allowed_upload_roots:
                candidate.unlink(missing_ok=True)
        redis_keys_removed = await cleanup_redis_sessions(user_ids, college_ids, device_ids)
        if asset_paths and any(Path(value).exists() for value in asset_paths):
            raise RuntimeError("Exact-ID QA cleanup left one or more uploaded fixture files behind")
        path.unlink(missing_ok=True)
        print(
            "Exact-ID cleanup verified zero users/devices/reservations/notifications/Outbox/"
            "colleges; "
            f"deleted {redis_keys_removed} indexed session/cache keys and "
            f"{len(asset_paths)} upload files."
        )
    finally:
        await engine.dispose()


async def cleanup_redis_sessions(
    user_ids: list[int], college_ids: list[int], device_ids: list[int]
) -> int:
    """Delete Redis state only under fixture-owned user, tenant, and device IDs."""
    client = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
    removed = 0
    try:
        for user_id in user_ids:
            user_key = f"lab:v2:auth:user-sessions:{user_id}"
            session_ids = await client.smembers(user_key)
            keys = [user_key]
            for session_id in session_ids:
                prefix = f"lab:v2:auth:session:{session_id}"
                keys.append(prefix)
                async for permission_key in client.scan_iter(match=f"{prefix}:permissions:v*"):
                    keys.append(permission_key)
            if keys:
                removed += int(await client.delete(*keys))
        for college_id in college_ids:
            scope = f"college:{college_id}"
            keys = [f"lab:v2:cache:catalog:version:{scope}"]
            async for key in client.scan_iter(match=f"lab:v2:catalog:devices:{scope}:*"):
                keys.append(key)
                if len(keys) >= 500:
                    removed += int(await client.delete(*keys))
                    keys.clear()
            if keys:
                removed += int(await client.delete(*keys))
        for device_id in device_ids:
            keys = [f"lab:v2:reservation:device:{device_id}"]
            async for key in client.scan_iter(match=f"lab:v2:reservation:{device_id}:*"):
                keys.append(key)
                if len(keys) >= 500:
                    removed += int(await client.delete(*keys))
                    keys.clear()
            if keys:
                removed += int(await client.delete(*keys))

        # Verify the bounded namespace is empty after deletion.
        for user_id in user_ids:
            if await client.exists(f"lab:v2:auth:user-sessions:{user_id}"):
                raise RuntimeError("QA cleanup left an indexed session key behind")
        for college_id in college_ids:
            scope = f"college:{college_id}"
            if await client.exists(f"lab:v2:cache:catalog:version:{scope}"):
                raise RuntimeError("QA cleanup left a catalog-version key behind")
            catalog_cache_keys = [
                key async for key in client.scan_iter(match=f"lab:v2:catalog:devices:{scope}:*")
            ]
            if catalog_cache_keys:
                raise RuntimeError("QA cleanup left a catalog cache key behind")
        for device_id in device_ids:
            if await client.exists(f"lab:v2:reservation:device:{device_id}"):
                raise RuntimeError("QA cleanup left a device-lock key behind")
            reservation_lock_keys = [
                key async for key in client.scan_iter(match=f"lab:v2:reservation:{device_id}:*")
            ]
            if reservation_lock_keys:
                raise RuntimeError("QA cleanup left a reservation-lock key behind")
        return removed
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "cleanup"))
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args()
    path = _fixture_path(args.manifest)
    if args.action == "create":
        if path.exists():
            raise SystemExit(f"Refusing to overwrite fixture manifest: {path}")
        manifest = asyncio.run(create_fixture(path))
        print(
            json.dumps(
                {
                    "run_id": manifest["run_id"],
                    "fixture_file": str(path),
                    "colleges": 2,
                    "students": sum(len(values) for values in manifest["student_ids"].values()),
                    "managers": 2,
                    "devices": 12,
                },
                ensure_ascii=False,
            )
        )
    else:
        asyncio.run(cleanup_fixture(path))
        print("Fixture rows were deleted by exact IDs; manifest removed.")


if __name__ == "__main__":
    main()
