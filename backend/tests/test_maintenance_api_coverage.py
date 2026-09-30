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
from app.infrastructure.db.models import Device, UploadAsset
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(user_id: int, username: str, college_id: int, role: str) -> Principal:
    permissions = (
        ("maintenance:manage", "device:read", "reservation:read:scope")
        if role in {"LAB_ADMIN", "SYS_ADMIN"}
        else ("device:read",)
    )
    return Principal(
        user_id=user_id,
        username=username,
        college_id=college_id,
        roles=(role,),
        token_type="access",
        token_id=f"maintenance-test-{user_id}",
        permissions=permissions,
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
    upload_dir: Path,
    *,
    upload_max_bytes: int = 128,
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
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _plan_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "plan_type": "ROUTINE",
        "title": "月度设备保养",
        "interval_value": 1,
        "interval_unit": "MONTH",
        "due_date": (date.today() + timedelta(days=30)).isoformat(),
        "active": True,
    }
    payload.update(updates)
    return payload


@pytest.mark.asyncio
async def test_maintenance_device_selector_filters_scope_search_and_deleted_rows(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, _other_student, manager, device, _other_device = (
        seeded
    )
    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None
        stored_device.asset_code = "CSE-GPU-042"
        lab_id = stored_device.lab_id
        assert lab_id is not None
        second = Device(
            name="GPU 显微工作站",
            asset_code="CSE-GPU-043",
            college_id=college.id,
            lab_id=lab_id,
            status="IDLE",
        )
        deleted = Device(
            name="已删除 GPU",
            asset_code="CSE-GPU-044",
            college_id=college.id,
            lab_id=lab_id,
            status="DELETED",
        )
        session.add_all([second, deleted])
        await session.commit()
        second_id = second.id
        deleted_id = deleted.id

    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(factory, actor, tmp_path) as client:
        page = await client.get("/api/v2/maintenance-devices?page=1&page_size=1&search=%20GPU%20")
        assert page.status_code == 200
        data = page.json()["data"]
        assert data["total"] == 2
        assert data["pages"] == 2
        assert len(data["items"]) == 1

        second_page = await client.get("/api/v2/maintenance-devices?page=2&page_size=1")
        assert second_page.status_code == 200
        assert second_page.json()["data"]["items"][0]["id"] in {device.id, second_id}
        assert deleted_id not in {item["id"] for item in second_page.json()["data"]["items"]}

        asset_code_search = await client.get("/api/v2/maintenance-devices?search=CSE-GPU-042")
        assert [row["id"] for row in asset_code_search.json()["data"]["items"]] == [device.id]

    actor["value"] = _principal(student.id, student.username, college.id, "STUDENT")
    async with _client(factory, actor, tmp_path) as client:
        forbidden = await client.get("/api/v2/maintenance-devices")
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_plan_http_lifecycle_and_scope_guards(seeded, tmp_path: Path) -> None:
    factory, college, _other_college, _student, _other_student, manager, device, other_device = (
        seeded
    )
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(factory, actor, tmp_path) as client:
        created = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-plans", json=_plan_payload()
        )
        assert created.status_code == 201
        plan = created.json()["data"]
        assert plan["title"] == "月度设备保养"
        assert plan["device_id"] == device.id

        filtered = await client.get(
            f"/api/v2/maintenance-plans?device_id={device.id}&active=true&page=1&page_size=5"
        )
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()["data"]["items"]] == [plan["id"]]

        updated = await client.put(
            f"/api/v2/maintenance-plans/{plan['id']}",
            json=_plan_payload(
                title="季度设备保养",
                due_date=(date.today() + timedelta(days=45)).isoformat(),
                active=False,
            ),
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["title"] == "季度设备保养"
        assert updated.json()["data"]["active"] is False

        inactive = await client.get("/api/v2/maintenance-plans?active=false")
        assert [item["id"] for item in inactive.json()["data"]["items"]] == [plan["id"]]

        missing = await client.put("/api/v2/maintenance-plans/999999", json=_plan_payload())
        assert missing.status_code == 404

        wrong_scope = await client.post(
            f"/api/v2/devices/{other_device.id}/maintenance-plans", json=_plan_payload()
        )
        assert wrong_scope.status_code == 404

    actor["value"] = _principal(manager.id, manager.username, college.id, "STUDENT")
    async with _client(factory, actor, tmp_path) as client:
        forbidden = await client.get("/api/v2/maintenance-plans")
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_evidence_cycle_is_idempotent_and_download_is_scoped(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, _other_student, manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(factory, actor, tmp_path) as client:
        plan_response = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-plans",
            json=_plan_payload(
                plan_type="CALIBRATION",
                title="工作站精度校准",
                due_date=date.today().isoformat(),
            ),
        )
        assert plan_response.status_code == 201
        plan_id = plan_response.json()["data"]["id"]

        upload = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-evidence",
            files={"file": ("calibration.pdf", b"%PDF-1", "application/pdf")},
        )
        assert upload.status_code == 201
        evidence = upload.json()["data"]
        assert evidence["content_type"] == "application/pdf"
        assert evidence["size_bytes"] == 6

        record_payload = {
            "cycle_due_date": date.today().isoformat(),
            "completed_date": date.today().isoformat(),
            "result": "PASSED",
            "notes": "校准合格",
        }
        without_evidence = await client.post(
            f"/api/v2/maintenance-plans/{plan_id}/records",
            headers={"Idempotency-Key": "calibration-no-evidence-01"},
            json=record_payload,
        )
        assert without_evidence.status_code == 422
        assert without_evidence.json()["code"] == "MAINTENANCE_EVIDENCE_REQUIRED"

        headers = {"Idempotency-Key": "calibration-cycle-record-0001"}
        body = {**record_payload, "evidence_asset_token": evidence["asset_token"]}
        first = await client.post(
            f"/api/v2/maintenance-plans/{plan_id}/records", headers=headers, json=body
        )
        retry = await client.post(
            f"/api/v2/maintenance-plans/{plan_id}/records", headers=headers, json=body
        )
        assert first.status_code == 201
        assert retry.status_code == 201
        record = first.json()["data"]
        assert retry.json()["data"]["id"] == record["id"]
        assert record["evidence_asset_token"] == evidence["asset_token"]

        records = await client.get(f"/api/v2/maintenance-plans/{plan_id}/records")
        assert records.status_code == 200
        assert [row["id"] for row in records.json()["data"]["items"]] == [record["id"]]

        download = await client.get(evidence["url"])
        assert download.status_code == 200
        assert download.content == b"%PDF-1"

        async with factory() as session:
            asset = await session.scalar(
                select(UploadAsset).where(UploadAsset.asset_token == evidence["asset_token"])
            )
            assert asset is not None
            asset.storage_path = str(tmp_path.parent / "outside-maintenance-proof.pdf")
            await session.commit()
        outside_path = await client.get(evidence["url"])
        assert outside_path.status_code == 404

        missing = await client.get("/api/v2/maintenance-evidence/not-a-real-token")
        assert missing.status_code == 404

    actor["value"] = _principal(manager.id, manager.username, college.id, "STUDENT")
    async with _client(factory, actor, tmp_path) as client:
        forbidden = await client.get(evidence["url"])
    assert forbidden.status_code == 403

    # A principal with the right permission and tenant but without ownership of
    # the device's lab must receive the same non-disclosing 404 as an unknown file.
    actor["value"] = _principal(student.id, student.username, college.id, "LAB_ADMIN")
    async with _client(factory, actor, tmp_path) as client:
        outside_scope = await client.get(evidence["url"])
    assert outside_scope.status_code == 404


@pytest.mark.asyncio
async def test_maintenance_upload_rejects_bad_files_and_enforces_storage_quota(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, _student, _other_student, manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(
        factory,
        actor,
        tmp_path,
        upload_max_bytes=8,
        upload_user_quota_bytes=6,
    ) as client:
        invalid_type = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-evidence",
            files={"file": ("proof.txt", b"plain", "text/plain")},
        )
        assert invalid_type.status_code == 422

        invalid_signature = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-evidence",
            files={"file": ("proof.pdf", b"not-pdf", "application/pdf")},
        )
        assert invalid_signature.status_code == 422

        too_large = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-evidence",
            files={"file": ("proof.pdf", b"%PDF-1234567", "application/pdf")},
        )
        assert too_large.status_code == 413

        uploaded = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-evidence",
            files={"file": ("proof.pdf", b"%PDF-1", "application/pdf")},
        )
        assert uploaded.status_code == 201

        over_quota = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-evidence",
            files={"file": ("second.pdf", b"%PDF-1", "application/pdf")},
        )
        assert over_quota.status_code == 413
        assert over_quota.json()["code"] == "UPLOAD_USER_QUOTA_EXCEEDED"

    async with factory() as session:
        assets = list((await session.scalars(select(UploadAsset))).all())
        assert len(assets) == 1
        assert assets[0].storage_path.startswith(str(tmp_path))


@pytest.mark.asyncio
async def test_maintenance_upload_rolls_back_asset_and_file_after_database_failure(
    seeded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v2 import maintenance as maintenance_api

    factory, college, _other_college, _student, _other_student, manager, device, _other_device = (
        seeded
    )
    collision_token = "duplicate-maintenance-asset-token-0001"
    async with factory() as session:
        session.add(
            UploadAsset(
                asset_token=collision_token,
                user_id=manager.id,
                college_id=college.id,
                original_name="prior.pdf",
                content_type="application/pdf",
                size_bytes=6,
                storage_path=str(tmp_path / "prior.pdf"),
            )
        )
        await session.commit()

    monkeypatch.setattr(maintenance_api.secrets, "token_urlsafe", lambda _size: collision_token)
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(
        factory,
        actor,
        tmp_path,
        raise_app_exceptions=False,
    ) as client:
        failed = await client.post(
            f"/api/v2/devices/{device.id}/maintenance-evidence",
            files={"file": ("duplicate.pdf", b"%PDF-1", "application/pdf")},
        )

    assert failed.status_code == 500
    assert not (tmp_path / f"{collision_token}.pdf").exists()
    async with factory() as session:
        stored = list(
            (
                await session.scalars(
                    select(UploadAsset).where(UploadAsset.asset_token == collision_token)
                )
            ).all()
        )
    assert len(stored) == 1
