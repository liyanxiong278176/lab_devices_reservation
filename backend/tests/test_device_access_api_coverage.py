from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    DeviceDocument,
    DeviceDocumentAcknowledgement,
    DeviceQualification,
    UploadAsset,
)
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(user_id: int, username: str, college_id: int, *roles: str) -> Principal:
    return Principal(
        user_id=user_id,
        username=username,
        college_id=college_id,
        roles=roles,
        token_type="access",
        token_id=f"test-{user_id}",
        permissions=("device:read", "reservation:create"),
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
    upload_dir: Path,
    *,
    upload_max_bytes: int = 16,
    upload_user_quota_bytes: int = 1024,
    raise_app_exceptions: bool = True,
) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        cors_origins=["http://test"],
        redis_url="redis://127.0.0.1:6379/15",
        enable_workers=False,
        rate_limit_enabled=False,
        upload_dir=str(upload_dir),
        upload_max_bytes=upload_max_bytes,
        upload_user_quota_bytes=upload_user_quota_bytes,
    )
    app = create_app(settings)

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_actor() -> Principal:
        return actor["value"]

    async def no_csrf() -> None:
        return None

    async def no_rate_limit() -> None:
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_actor
    app.dependency_overrides[enforce_csrf] = no_csrf
    app.dependency_overrides[enforce_authenticated_rate_limit] = no_rate_limit
    transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _add_document(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    device_id: int,
    college_id: int,
    created_by: int,
    document_type: str,
    version: str,
    active: bool = True,
    requires_ack: bool = True,
) -> int:
    async with session_factory() as session:
        asset = UploadAsset(
            asset_token=f"document-{device_id}-{document_type}-{version}",
            user_id=created_by,
            college_id=college_id,
            original_name=f"{document_type}.pdf",
            content_type="application/pdf",
            size_bytes=5,
            storage_path="/tmp/document.pdf",
        )
        session.add(asset)
        await session.flush()
        document = DeviceDocument(
            device_id=device_id,
            college_id=college_id,
            asset_id=asset.id,
            document_type=document_type,
            title=f"{document_type} 指引",
            version=version,
            requires_ack=requires_ack,
            active=active,
            created_by=created_by,
        )
        session.add(document)
        await session.commit()
        return document.id


@pytest.mark.asyncio
async def test_safety_documents_latest_per_type_and_acknowledgement_is_idempotent(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(student.id, student.username, college.id, "STUDENT")}
    old_manual_id = await _add_document(
        factory,
        device_id=device.id,
        college_id=college.id,
        created_by=student.id,
        document_type="MANUAL",
        version="1.0",
    )
    latest_manual_id = await _add_document(
        factory,
        device_id=device.id,
        college_id=college.id,
        created_by=student.id,
        document_type="MANUAL",
        version="2.0",
    )
    safety_id = await _add_document(
        factory,
        device_id=device.id,
        college_id=college.id,
        created_by=student.id,
        document_type="SAFETY",
        version="A",
    )
    await _add_document(
        factory,
        device_id=device.id,
        college_id=college.id,
        created_by=student.id,
        document_type="SOP",
        version="draft",
        active=False,
    )
    await _add_document(
        factory,
        device_id=device.id,
        college_id=college.id,
        created_by=student.id,
        document_type="SOP",
        version="read-only",
        requires_ack=False,
    )

    async with _client(factory, actor, tmp_path) as client:
        response = await client.get(f"/api/v2/devices/{device.id}/safety-documents")
        assert response.status_code == 200
        rows = response.json()["data"]
        assert {row["id"] for row in rows} == {latest_manual_id, safety_id}
        assert old_manual_id not in {row["id"] for row in rows}
        assert all(row["url"].startswith("/api/v2/device-documents/") for row in rows)

        first_ack = await client.post(
            f"/api/v2/devices/{device.id}/safety-ack", json={"reservation_id": None}
        )
        assert first_ack.status_code == 200
        assert first_ack.json()["data"] == {
            "device_id": device.id,
            "acknowledged": True,
            "version": "2.0",
        }
        second_ack = await client.post(
            f"/api/v2/devices/{device.id}/safety-ack", json={"reservation_id": None}
        )
        assert second_ack.status_code == 200

    async with factory() as session:
        acknowledgements = list(
            (
                await session.scalars(
                    select(DeviceDocumentAcknowledgement).where(
                        DeviceDocumentAcknowledgement.user_id == student.id
                    )
                )
            ).all()
        )
        assert {row.document_id for row in acknowledgements} == {latest_manual_id, safety_id}
        assert all(row.document_version in {"2.0", "A"} for row in acknowledgements)


@pytest.mark.asyncio
async def test_acknowledging_without_required_documents_returns_conflict(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(student.id, student.username, college.id, "STUDENT")}
    async with _client(factory, actor, tmp_path) as client:
        response = await client.post(
            f"/api/v2/devices/{device.id}/safety-ack", json={"reservation_id": None}
        )
    assert response.status_code == 409
    assert response.json()["code"] == "SAFETY_DOCUMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_qualification_upload_validates_type_size_signature_and_quota(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(student.id, student.username, college.id, "STUDENT")}
    async with _client(
        factory,
        actor,
        tmp_path,
        upload_max_bytes=8,
        upload_user_quota_bytes=6,
    ) as client:
        invalid_type = await client.post(
            f"/api/v2/devices/{device.id}/qualification-uploads",
            files={"file": ("proof.txt", b"plain", "text/plain")},
        )
        assert invalid_type.status_code == 422
        assert invalid_type.json()["code"] == "QUALIFICATION_UPLOAD_TYPE_INVALID"

        invalid_signature = await client.post(
            f"/api/v2/devices/{device.id}/qualification-uploads",
            files={"file": ("proof.pdf", b"not-pdf", "application/pdf")},
        )
        assert invalid_signature.status_code == 422
        assert invalid_signature.json()["code"] == "UPLOAD_CONTENT_INVALID"

        too_large = await client.post(
            f"/api/v2/devices/{device.id}/qualification-uploads",
            files={"file": ("proof.pdf", b"%PDF-123456789", "application/pdf")},
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "UPLOAD_TOO_LARGE"

        uploaded = await client.post(
            f"/api/v2/devices/{device.id}/qualification-uploads",
            files={"file": (" proof.pdf ", b"%PDF-1", "application/pdf")},
        )
        assert uploaded.status_code == 201
        asset = uploaded.json()["data"]
        assert asset["name"] == " proof.pdf "
        assert asset["content_type"] == "application/pdf"
        assert asset["size_bytes"] == 6
        stored_path = next(tmp_path.glob("*.pdf"))
        assert stored_path.read_bytes() == b"%PDF-1"

        over_quota = await client.post(
            f"/api/v2/devices/{device.id}/qualification-uploads",
            files={"file": ("again.pdf", b"%PDF-2", "application/pdf")},
        )
        assert over_quota.status_code == 413
        assert over_quota.json()["code"] == "UPLOAD_USER_QUOTA_EXCEEDED"


@pytest.mark.asyncio
async def test_qualification_upload_accepts_supported_image_signatures(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(student.id, student.username, college.id, "STUDENT")}
    uploads = (
        ("photo.jpg", b"\xff\xd8\xff", "image/jpeg", ".jpg"),
        ("scan.png", b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
        ("manual.webp", b"RIFF1234WEBPdata", "image/webp", ".webp"),
    )
    async with _client(factory, actor, tmp_path) as client:
        for filename, content, content_type, suffix in uploads:
            response = await client.post(
                f"/api/v2/devices/{device.id}/qualification-uploads",
                files={"file": (filename, content, content_type)},
            )
            assert response.status_code == 201
            assert response.json()["data"]["content_type"] == content_type
            stored_file = next(tmp_path.glob(f"*{suffix}"))
            assert stored_file.read_bytes() == content


@pytest.mark.asyncio
async def test_failed_qualification_upload_commit_removes_written_file(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(student.id, student.username, college.id, "STUDENT")}
    original_commit = AsyncSession.commit

    async def fail_when_upload_is_pending(session: AsyncSession) -> None:
        if any(isinstance(item, UploadAsset) for item in session.new):
            raise RuntimeError("simulated asset metadata commit failure")
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", fail_when_upload_is_pending)
    async with _client(factory, actor, tmp_path, raise_app_exceptions=False) as client:
        response = await client.post(
            f"/api/v2/devices/{device.id}/qualification-uploads",
            files={"file": ("failure.pdf", b"%PDF-1", "application/pdf")},
        )
    assert response.status_code == 500
    assert list(tmp_path.iterdir()) == []
    async with factory() as session:
        assert await session.scalar(select(UploadAsset.id)) is None


@pytest.mark.asyncio
async def test_qualification_submission_review_scope_and_access_snapshot(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, _other_student, manager, device, other_device = (
        seeded
    )
    actor = {"value": _principal(student.id, student.username, college.id, "STUDENT")}
    async with factory() as session:
        current_device = await session.get(type(device), device.id)
        current_device.requires_qualification = True
        current_device.requires_safety_ack = True
        await session.commit()

    async with _client(factory, actor, tmp_path) as client:
        missing = await client.get(f"/api/v2/devices/{device.id}/qualifications/mine")
        assert missing.status_code == 200
        assert missing.json()["data"] is None

        foreign_asset = await client.post(
            f"/api/v2/devices/{device.id}/qualifications",
            json={"qualification_type": "  LASER  ", "asset_id": 999999, "note": "n"},
        )
        assert foreign_asset.status_code == 422
        assert foreign_asset.json()["code"] == "QUALIFICATION_ASSET_INVALID"

        uploaded = await client.post(
            f"/api/v2/devices/{device.id}/qualification-uploads",
            files={"file": ("qualification.pdf", b"%PDF-verified", "application/pdf")},
        )
        assert uploaded.status_code == 201
        asset_id = uploaded.json()["data"]["asset_id"]
        submitted = await client.post(
            f"/api/v2/devices/{device.id}/qualifications",
            json={
                "qualification_type": "  LASER  ",
                "asset_id": asset_id,
                "note": "  initial note  ",
            },
        )
        assert submitted.status_code == 201
        qualification_id = submitted.json()["data"]["id"]
        assert submitted.json()["data"]["qualification_type"] == "LASER"
        assert submitted.json()["data"]["note"] == "initial note"

        my_row = await client.get(f"/api/v2/devices/{device.id}/qualifications/mine")
        assert my_row.json()["data"]["id"] == qualification_id
        student_list = await client.get(f"/api/v2/devices/{device.id}/qualifications")
        assert student_list.status_code == 403
        forbidden_review = await client.patch(
            f"/api/v2/devices/{device.id}/qualifications/{qualification_id}",
            json={"status": "REJECTED", "note": "outside manager scope"},
        )
        assert forbidden_review.status_code == 403

        actor["value"] = _principal(manager.id, manager.username, college.id, "LAB_ADMIN")
        manager_list = await client.get(f"/api/v2/devices/{device.id}/qualifications")
        assert manager_list.status_code == 200
        assert [row["id"] for row in manager_list.json()["data"]] == [qualification_id]

        expired = await client.patch(
            f"/api/v2/devices/{device.id}/qualifications/{qualification_id}",
            json={
                "status": "APPROVED",
                "valid_until": (date.today() - timedelta(days=1)).isoformat(),
            },
        )
        assert expired.status_code == 422
        assert expired.json()["code"] == "QUALIFICATION_DATE_INVALID"

        approved = await client.patch(
            f"/api/v2/devices/{device.id}/qualifications/{qualification_id}",
            json={
                "status": "APPROVED",
                "valid_until": (date.today() + timedelta(days=30)).isoformat(),
            },
        )
        assert approved.status_code == 200
        assert approved.json()["data"]["reviewed_by"] == manager.id

        missing_review = await client.patch(
            f"/api/v2/devices/{device.id}/qualifications/999999",
            json={"status": "REJECTED", "note": "not found"},
        )
        assert missing_review.status_code == 404
        assert missing_review.json()["code"] == "QUALIFICATION_NOT_FOUND"

        access = await client.get(f"/api/v2/devices/{device.id}/access")
        assert access.status_code == 200
        assert access.json()["data"]["safety_required"] is True
        assert access.json()["data"]["qualification_required"] is True

        actor["value"] = _principal(student.id, student.username, college.id, "STUDENT")
        resubmitted = await client.post(
            f"/api/v2/devices/{device.id}/qualifications",
            json={"qualification_type": " LASER_REFRESH ", "note": " updated "},
        )
        assert resubmitted.status_code == 201
        assert resubmitted.json()["data"]["status"] == "PENDING"
        assert resubmitted.json()["data"]["reviewed_by"] is None
        assert resubmitted.json()["data"]["valid_until"] is None
        assert resubmitted.json()["data"]["note"] == "updated"
        assert resubmitted.json()["data"]["qualification_type"] == "LASER_REFRESH"

        forbidden_cross_tenant = await client.get(
            f"/api/v2/devices/{other_device.id}/qualifications/mine"
        )
        assert forbidden_cross_tenant.status_code == 404

    async with factory() as session:
        row = await session.scalar(
            select(DeviceQualification).where(
                DeviceQualification.device_id == device.id,
                DeviceQualification.user_id == student.id,
            )
        )
        assert row is not None
        assert row.status == "PENDING"
        assert row.reviewed_by is None
