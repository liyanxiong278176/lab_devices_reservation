from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import Device, RepairReport, UploadAsset
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(user, role: str) -> Principal:
    permissions = (
        ("device:read", "repair:create", "repair:read:own", "repair:confirm")
        if role == "STUDENT"
        else ("device:read", "repair:handle", "repair:read:scope")
    )
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=(role,),
        token_type="access",
        token_id=f"repair-api-{user.id}",
        permissions=permissions,
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
    *,
    upload_dir: str | None = None,
    upload_max_bytes: int = 5 * 1024 * 1024,
    raise_app_exceptions: bool = True,
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(
            environment="test",
            mysql_dsn="sqlite+aiosqlite:///:memory:",
            cors_origins=["http://test"],
            redis_url="redis://127.0.0.1:6379/15",
            rate_limit_enabled=False,
            upload_dir=upload_dir or ".data/test-uploads",
            upload_max_bytes=upload_max_bytes,
        )
    )

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
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_repair_upload_scope_and_full_report_resolution_flow(
    seeded, monkeypatch, tmp_path
) -> None:
    from app.application import repairs as repair_service

    factory, _college, _other_college, student, other_student, manager, device, _ = seeded

    async def skip_fast_cache_bump(_app, _college_id):
        return True

    monkeypatch.setattr(repair_service, "sync_catalog_cache_bump", skip_fast_cache_bump)
    student_actor = {"value": _principal(student, "STUDENT")}

    async with _client(factory, student_actor, upload_dir=str(tmp_path)) as client:
        unsupported = await client.post(
            "/api/v2/repair-uploads",
            files={"file": ("proof.txt", b"not an image", "text/plain")},
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["code"] == "UPLOAD_TYPE_INVALID"

        invalid_signature = await client.post(
            "/api/v2/repair-uploads",
            files={"file": ("proof.png", b"not a png", "image/png")},
        )
        assert invalid_signature.status_code == 422
        assert invalid_signature.json()["code"] == "UPLOAD_CONTENT_INVALID"

        uploaded = await client.post(
            "/api/v2/repair-uploads",
            files={
                "file": (
                    "power-supply.png",
                    b"\x89PNG\r\n\x1a\nvalid-test-image-bytes",
                    "image/png",
                )
            },
        )
        assert uploaded.status_code == 201
        image_url = uploaded.json()["data"]["url"]

        created = await client.post(
            "/api/v2/repair-reports",
            json={
                "device_id": device.id,
                "title": "工作站电源无法启动",
                "description": "按下电源后没有指示灯",
                "image_urls": [image_url],
                "priority": "IMPORTANT",
            },
        )
        assert created.status_code == 201
        report_id = created.json()["data"]["id"]
        assert created.json()["data"]["status"] == "PENDING"
        assert created.json()["data"]["priority"] == "IMPORTANT"

        mine = await client.get("/api/v2/repair-reports/mine?page=1&size=5")
        assert mine.status_code == 200
        assert mine.json()["data"]["items"][0]["id"] == report_id

        image = await client.get(image_url)
        assert image.status_code == 200
        assert image.content.startswith(b"\x89PNG\r\n\x1a\n")

    other_actor = {"value": _principal(other_student, "STUDENT")}
    async with _client(factory, other_actor, upload_dir=str(tmp_path)) as client:
        cross_college_image = await client.get(image_url)
        assert cross_college_image.status_code == 404

    manager_actor = {"value": _principal(manager, "LAB_ADMIN")}
    async with _client(factory, manager_actor, upload_dir=str(tmp_path)) as client:
        invalid_filter = await client.get("/api/v2/repair-reports?status=NOT_A_STATUS")
        assert invalid_filter.status_code == 422
        assert invalid_filter.json()["code"] == "REPAIR_STATUS_INVALID"

        pending = await client.get("/api/v2/repair-reports?status=PENDING&page=1&size=5")
        assert pending.status_code == 200
        assert report_id in {row["id"] for row in pending.json()["data"]["items"]}

        taken = await client.post(f"/api/v2/repair-reports/{report_id}/take")
        assert taken.status_code == 200
        assert taken.json()["data"]["status"] == "PROCESSING"

        resolved = await client.post(
            f"/api/v2/repair-reports/{report_id}/resolve",
            json={"resolution_note": "更换电源模块并完成通电测试"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["data"]["status"] == "RESOLVED"

        worklogs = await client.get(f"/api/v2/repair-reports/{report_id}/worklogs")
        assert worklogs.status_code == 200
        assert [item["status"] for item in worklogs.json()["data"]] == [
            "PENDING",
            "PROCESSING",
            "RESOLVED",
        ]

    student_actor["value"] = _principal(student, "STUDENT")
    async with _client(factory, student_actor, upload_dir=str(tmp_path)) as client:
        confirmed = await client.post(
            f"/api/v2/repair-reports/{report_id}/confirm",
            json={"confirmed": True, "note": "设备已恢复，可以正常使用"},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["data"]["status"] == "COMPLETED"

    async with factory() as session:
        stored_report = await session.get(RepairReport, report_id)
        stored_device = await session.get(Device, device.id)
        assert stored_report is not None and stored_report.status == "COMPLETED"
        assert stored_device is not None and stored_device.status == "IDLE"


@pytest.mark.asyncio
async def test_manager_can_reject_pending_repair_over_http(seeded, monkeypatch) -> None:
    from app.application import repairs as repair_service

    factory, _college, _other_college, student, _other_student, manager, device, _ = seeded

    async def skip_fast_cache_bump(_app, _college_id):
        return True

    monkeypatch.setattr(repair_service, "sync_catalog_cache_bump", skip_fast_cache_bump)
    student_actor = {"value": _principal(student, "STUDENT")}
    async with _client(factory, student_actor) as client:
        created = await client.post(
            "/api/v2/repair-reports",
            json={
                "device_id": device.id,
                "title": "设备连接异常",
                "description": "网络线松动",
            },
        )
        assert created.status_code == 201
        report_id = created.json()["data"]["id"]

    manager_actor = {"value": _principal(manager, "LAB_ADMIN")}
    async with _client(factory, manager_actor) as client:
        rejected = await client.post(
            f"/api/v2/repair-reports/{report_id}/reject",
            json={"resolution_note": "现场检查后确认为外部网络故障"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["data"]["status"] == "REJECTED"

    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None and stored_device.status == "IDLE"


@pytest.mark.asyncio
async def test_repair_image_validation_size_and_missing_file_paths(seeded, tmp_path: Path) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _ = seeded
    actor = {"value": _principal(student, "STUDENT")}
    async with _client(
        factory,
        actor,
        upload_dir=str(tmp_path),
        upload_max_bytes=8,
    ) as client:
        omitted = await client.post(
            "/api/v2/repair-reports",
            json={
                "device_id": device.id,
                "title": "插座接触不良",
                "image_urls": None,
            },
        )
        assert omitted.status_code == 201

        invalid_urls = await client.post(
            "/api/v2/repair-reports",
            json={
                "device_id": device.id,
                "title": "电源线破损",
                "image_urls": ["http://untrusted.example/image.png"],
            },
        )
        assert invalid_urls.status_code == 422

        too_large = await client.post(
            "/api/v2/repair-uploads",
            files={"file": ("large.png", b"\x89PNG\r\n\x1a\nlarge", "image/png")},
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "UPLOAD_TOO_LARGE"

        uploaded = await client.post(
            "/api/v2/repair-uploads",
            files={"file": ("missing.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
        assert uploaded.status_code == 201
        image_url = uploaded.json()["data"]["url"]
        token = image_url.rsplit("/", 1)[-1]
        async with factory() as session:
            asset = await session.scalar(
                select(UploadAsset).where(UploadAsset.asset_token == token)
            )
            assert asset is not None and asset.college_id == college.id
            asset.storage_path = str(tmp_path.parent / "outside-repair-image.png")
            await session.commit()

        outside_path = await client.get(image_url)
        assert outside_path.status_code == 404


@pytest.mark.asyncio
async def test_failed_repair_upload_commit_removes_written_file(
    seeded, monkeypatch, tmp_path: Path
) -> None:
    factory, _college, _other_college, student, _other_student, _manager, _device, _ = seeded
    actor = {"value": _principal(student, "STUDENT")}
    original_commit = AsyncSession.commit

    async def fail_when_upload_is_pending(session: AsyncSession) -> None:
        if any(isinstance(item, UploadAsset) for item in session.new):
            raise RuntimeError("simulated repair asset metadata commit failure")
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", fail_when_upload_is_pending)
    async with _client(
        factory,
        actor,
        upload_dir=str(tmp_path),
        raise_app_exceptions=False,
    ) as client:
        response = await client.post(
            "/api/v2/repair-uploads",
            files={"file": ("failure.png", b"\x89PNG\r\n\x1a\nvalid", "image/png")},
        )

    assert response.status_code == 500
    assert list(tmp_path.iterdir()) == []
    async with factory() as session:
        assert await session.scalar(select(UploadAsset.id)) is None
