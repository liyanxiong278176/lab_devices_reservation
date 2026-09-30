from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
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
from app.infrastructure.db.operational_bootstrap import (
    backfill_unfinished_handovers,
    ensure_operational_metadata,
)
from sqlalchemy import select


@pytest.mark.asyncio
async def test_handover_backfill_maps_active_states_and_preserves_existing_evidence(seeded) -> None:
    factory, college, _, student, _, manager, device, _ = seeded
    now = datetime(2026, 9, 28, 12)
    async with factory() as session:
        reservations = [
            Reservation(
                college_id=college.id,
                user_id=student.id,
                device_id=device.id,
                start_date=now.date(),
                end_date=now.date(),
                status=status,
                handover_status=handover_status,
                purpose=f"case-{index}",
                created_at=now,
            )
            for index, (status, handover_status) in enumerate(
                [
                    ("PENDING", "NOT_REQUIRED"),
                    ("APPROVED", "EXCEPTION"),
                    ("IN_USE", "RETURN_PENDING"),
                    ("IN_USE", "NOT_REQUIRED"),
                    ("IN_USE", "NOT_REQUIRED"),
                    ("IN_USE", "NOT_REQUIRED"),
                ]
            )
        ]
        session.add_all(reservations)
        await session.flush()
        session.add_all(
            [
                DeviceHandover(
                    reservation_id=reservations[1].id,
                    device_id=device.id,
                    user_id=student.id,
                    college_id=college.id,
                    status="EXCEPTION",
                    handover_note="负责人记录的异常",
                ),
                DeviceHandover(
                    reservation_id=reservations[2].id,
                    device_id=device.id,
                    user_id=student.id,
                    college_id=college.id,
                    status="RETURN_PENDING",
                ),
                DeviceHandover(
                    reservation_id=reservations[3].id,
                    device_id=device.id,
                    user_id=student.id,
                    college_id=college.id,
                    status="HANDED_OVER",
                    handover_by=manager.id,
                    handover_at=now,
                ),
                DeviceHandover(
                    reservation_id=reservations[4].id,
                    device_id=device.id,
                    user_id=student.id,
                    college_id=college.id,
                    status="HANDED_OVER",
                    handover_note="保留既有记录",
                ),
            ]
        )
        await session.flush()

        await backfill_unfinished_handovers(session, now)
        await session.commit()

        refreshed = list(
            (
                await session.scalars(
                    select(Reservation).where(
                        Reservation.id.in_([item.id for item in reservations])
                    )
                )
            ).all()
        )
        handovers = list(
            (
                await session.scalars(
                    select(DeviceHandover).where(
                        DeviceHandover.reservation_id.in_([item.id for item in reservations])
                    )
                )
            ).all()
        )
        handovers_by_reservation = {item.reservation_id: item for item in handovers}
        by_purpose = {item.purpose: item for item in refreshed}

        assert by_purpose["case-0"].handover_status == "PENDING"
        assert by_purpose["case-1"].handover_status == "EXCEPTION"
        assert handovers_by_reservation[reservations[1].id].handover_note == "负责人记录的异常"
        assert by_purpose["case-2"].handover_status == "RETURN_PENDING"
        assert by_purpose["case-3"].handover_status == "HANDED_OVER"
        assert by_purpose["case-4"].handover_status == "LEGACY_IN_USE"
        assert handovers_by_reservation[reservations[4].id].handover_note == "保留既有记录"
        assert by_purpose["case-5"].handover_status == "LEGACY_IN_USE"
        assert "统一交接规则" in handovers_by_reservation[reservations[5].id].handover_note
        assert len(handovers) == len(reservations)


@pytest.mark.asyncio
async def test_metadata_bootstrap_creates_only_missing_active_documents_idempotently(
    seeded,
    tmp_path: Path,
) -> None:
    factory, college, other_college, _, _, _, device, other_device = seeded
    async with factory() as session:
        role = await session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
        assert role is not None
        admin = User(
            username="ops-bootstrap-admin",
            password_hash="test",
            real_name="运行管理员",
            college_id=college.id,
            roles=[role],
            status=1,
        )
        stored_special = await session.get(Device, device.id)
        stored_regular = await session.get(Device, other_device.id)
        assert stored_special is not None and stored_regular is not None
        stored_special.model = " F79300 "
        stored_special.asset_code = None
        stored_regular.asset_code = None
        deleted = Device(
            name="已删除设备",
            college_id=other_college.id,
            status="DELETED",
        )
        session.add_all([admin, deleted])
        await session.flush()
        existing_asset = UploadAsset(
            asset_token="existing-sop-token",
            user_id=admin.id,
            college_id=other_college.id,
            original_name="existing-sop.md",
            content_type="text/markdown",
            size_bytes=5,
            storage_path="existing-sop.md",
        )
        session.add(
            DeviceDocument(
                device_id=other_device.id,
                college_id=other_college.id,
                document_type="SOP",
                title="Existing SOP",
                version="2.0",
                active=True,
                requires_ack=False,
                created_by=admin.id,
                published_at=datetime(2026, 1, 1),
                asset=existing_asset,
            )
        )
        await session.commit()
        admin_id = admin.id
        deleted_id = deleted.id

    settings = Settings(
        environment="test",
        _env_file=None,
        upload_dir=str(tmp_path / "private-uploads"),
    )
    await ensure_operational_metadata(factory, settings)
    await ensure_operational_metadata(factory, settings)

    async with factory() as session:
        docs = list((await session.scalars(select(DeviceDocument))).all())
        active_by_device_and_type = {
            (document.device_id, document.document_type): document
            for document in docs
            if document.active
        }
        assert len(docs) == 4
        assert len(active_by_device_and_type) == 4
        assert (device.id, "SOP") in active_by_device_and_type
        assert (device.id, "SAFETY") in active_by_device_and_type
        assert (other_device.id, "SAFETY") in active_by_device_and_type
        assert (other_device.id, "SOP") in active_by_device_and_type
        assert (deleted_id, "SOP") not in active_by_device_and_type

        special = await session.get(Device, device.id)
        regular = await session.get(Device, other_device.id)
        assert special is not None and regular is not None
        assert special.asset_code == f"LAB-{device.id:06d}"
        assert special.risk_level == "CRITICAL"
        assert special.requires_safety_ack is True
        assert special.requires_qualification is True
        assert special.allow_external_loan is True
        assert regular.asset_code == f"LAB-{other_device.id:06d}"

        safety_doc = active_by_device_and_type[(device.id, "SAFETY")]
        assert safety_doc.requires_ack is True
        asset = await session.get(UploadAsset, safety_doc.asset_id)
        assert asset is not None
        assert Path(asset.storage_path).exists()
        assert asset.user_id == admin_id


@pytest.mark.asyncio
async def test_metadata_bootstrap_without_admin_still_backfills_and_commits(
    seeded,
    tmp_path: Path,
) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        session.add(
            Reservation(
                college_id=college.id,
                user_id=student.id,
                device_id=device.id,
                start_date=datetime(2026, 9, 28).date(),
                end_date=datetime(2026, 9, 28).date(),
                status="PENDING",
                purpose="bootstrap compatibility",
            )
        )
        await session.commit()

    await ensure_operational_metadata(
        factory,
        Settings(environment="test", _env_file=None, upload_dir=str(tmp_path / "uploads")),
    )

    async with factory() as session:
        handovers = list((await session.scalars(select(DeviceHandover))).all())
        documents = list((await session.scalars(select(DeviceDocument))).all())
        assert len(handovers) == 1
        assert handovers[0].status == "PENDING"
        assert documents == []
