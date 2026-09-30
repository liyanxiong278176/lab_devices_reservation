from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import UploadAsset
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(user_id: int, username: str, college_id: int, role: str) -> Principal:
    permissions = (
        ("device:read", "device:documents:manage")
        if role in {"LAB_ADMIN", "SYS_ADMIN"}
        else ("device:read",)
        if role == "STUDENT"
        else ()
    )
    return Principal(
        user_id=user_id,
        username=username,
        college_id=college_id,
        roles=(role,),
        token_type="access",
        token_id=f"device-documents-test-{user_id}",
        permissions=permissions,
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
    upload_dir: Path,
    *,
    upload_max_bytes: int = 128,
    upload_user_quota_bytes: int = 4096,
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
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _form(document_type: str = "MANUAL", **updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "document_type": document_type,
        "title": "  设备安全手册  ",
        "version": " 1.0 ",
        "requires_ack": "true",
    }
    values.update(updates)
    return values


@pytest.mark.asyncio
async def test_document_upload_replaces_previous_version_and_enforces_download_scope(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, _student, other_student, manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(factory, actor, tmp_path) as client:
        first = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form("MANUAL"),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
        assert first.status_code == 201
        first_data = first.json()["data"]
        assert first_data["title"] == "设备安全手册"
        assert first_data["version"] == "1.0"

        second = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form("MANUAL", title="新版手册", version="2.0"),
            files={"file": ("manual.md", "# 操作说明\n".encode(), "text/markdown")},
        )
        assert second.status_code == 201
        second_data = second.json()["data"]
        assert second_data["id"] != first_data["id"]

        listed = await client.get(f"/api/v2/devices/{device.id}/documents")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["data"]] == [second_data["id"]]

        download = await client.get(second_data["url"])
        assert download.status_code == 200
        assert download.content == "# 操作说明\n".encode()

        archived = await client.delete(f"/api/v2/devices/{device.id}/documents/{second_data['id']}")
        assert archived.status_code == 200
        inactive_download = await client.get(second_data["url"])
        assert inactive_download.status_code == 404
        missing_archive = await client.delete(
            f"/api/v2/devices/{device.id}/documents/{second_data['id']}"
        )
        assert missing_archive.status_code == 404

        missing_token = await client.get("/api/v2/device-documents/unknown-document-token")
        assert missing_token.status_code == 404

        active_document = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form("SAFETY", title="当前安全检查清单", version="1.0"),
            files={"file": ("safety.pdf", b"%PDF-1", "application/pdf")},
        )
        assert active_document.status_code == 201
        active_document_data = active_document.json()["data"]

    actor["value"] = _principal(
        other_student.id,
        other_student.username,
        other_student.college_id,
        "LAB_ADMIN",
    )
    async with _client(factory, actor, tmp_path) as client:
        foreign_tenant = await client.get(active_document_data["url"])
    assert foreign_tenant.status_code == 404

    actor["value"] = _principal(manager.id, manager.username, None, "SYS_ADMIN")
    async with _client(factory, actor, tmp_path) as client:
        global_admin_download = await client.get(active_document_data["url"])
    assert global_admin_download.status_code == 200

    actor["value"] = _principal(_student.id, _student.username, college.id, "LAB_ADMIN")
    async with _client(factory, actor, tmp_path) as client:
        unassigned_manager = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
    assert unassigned_manager.status_code == 403

    async with _client(factory, actor, tmp_path) as client:
        unassigned_archive = await client.delete(
            f"/api/v2/devices/{device.id}/documents/{active_document_data['id']}"
        )
    assert unassigned_archive.status_code == 403

    actor["value"] = _principal(other_student.id, other_student.username, college.id, "STUDENT")
    async with _client(factory, actor, tmp_path) as client:
        forbidden = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
    assert forbidden.status_code == 403

    actor["value"] = _principal(_student.id, _student.username, college.id, "GUEST")
    async with _client(factory, actor, tmp_path) as client:
        no_read_list = await client.get(f"/api/v2/devices/{device.id}/documents")
        no_read_download = await client.get(active_document_data["url"])
        no_manage_archive = await client.delete(
            f"/api/v2/devices/{device.id}/documents/{active_document_data['id']}"
        )
    assert no_read_list.status_code == 403
    assert no_read_download.status_code == 403
    assert no_manage_archive.status_code == 403


@pytest.mark.asyncio
async def test_document_upload_checks_metadata_content_size_and_quota(
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
        upload_max_bytes=12,
        upload_user_quota_bytes=12,
    ) as client:
        bad_kind = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form("OTHER"),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
        assert bad_kind.status_code == 422

        short_title = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(title=" "),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
        assert short_title.status_code == 422

        empty_version = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(version=" "),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
        assert empty_version.status_code == 422

        long_title = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(title="长" * 201),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
        assert long_title.status_code == 422

        long_version = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(version="v" * 41),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
        assert long_version.status_code == 422

        unsupported = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(),
            files={"file": ("manual.bin", b"data", "application/octet-stream")},
        )
        assert unsupported.status_code == 422

        mismatch = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(),
            files={"file": ("manual.pdf", b"not a PDF", "application/pdf")},
        )
        assert mismatch.status_code == 422

        too_large = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(),
            files={"file": ("manual.pdf", b"%PDF-123456789012", "application/pdf")},
        )
        assert too_large.status_code == 413

        valid = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form("SAFETY"),
            files={"file": ("safety.txt", b"safety guide", "text/plain")},
        )
        assert valid.status_code == 201

        over_quota = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form("SOP"),
            files={"file": ("sop.txt", b"more guide", "text/plain")},
        )
        assert over_quota.status_code == 413
        assert over_quota.json()["code"] == "UPLOAD_USER_QUOTA_EXCEEDED"

    async with factory() as session:
        assets = list((await session.scalars(select(UploadAsset))).all())
        assert len(assets) == 1


@pytest.mark.asyncio
async def test_document_signature_validation_accepts_supported_binary_formats(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, _student, _other_student, manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    samples = [
        ("manual.pdf", b"%PDF-1", "application/pdf"),
        ("manual.jpg", b"\xff\xd8\xffimage", "image/jpeg"),
        ("manual.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
        ("manual.webp", b"RIFF0000WEBP", "image/webp"),
        ("manual.md", b"# Guide", "text/markdown"),
        ("manual.txt", b"Plain guide", "text/plain"),
    ]
    async with _client(factory, actor, tmp_path) as client:
        for index, file in enumerate(samples):
            response = await client.post(
                f"/api/v2/devices/{device.id}/documents",
                data=_form(("MANUAL", "SOP", "SAFETY")[index % 3], version=str(index + 1)),
                files={"file": file},
            )
            assert response.status_code == 201, (file[2], response.text)

        blank_text = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form("MANUAL"),
            files={"file": ("blank.txt", b" \r\n\t", "text/plain")},
        )
        assert blank_text.status_code == 422

        bad_webp = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form("MANUAL"),
            files={"file": ("bad.webp", b"RIFF0000NOPE", "image/webp")},
        )
        assert bad_webp.status_code == 422


@pytest.mark.asyncio
async def test_document_download_rejects_paths_outside_private_upload_root(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, _student, _other_student, manager, device, _other_device = (
        seeded
    )
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(factory, actor, tmp_path) as client:
        uploaded = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(),
            files={"file": ("manual.pdf", b"%PDF-1", "application/pdf")},
        )
        assert uploaded.status_code == 201
        data = uploaded.json()["data"]

        async with factory() as session:
            asset = await session.scalar(
                select(UploadAsset).where(UploadAsset.asset_token == data["url"].rsplit("/", 1)[-1])
            )
            assert asset is not None
            asset.storage_path = str(tmp_path.parent / "outside-document.pdf")
            await session.commit()

        outside = await client.get(data["url"])
        assert outside.status_code == 404


@pytest.mark.asyncio
async def test_document_upload_removes_file_after_database_collision(
    seeded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v2 import device_documents as documents_api

    factory, college, _other_college, _student, _other_student, manager, device, _other_device = (
        seeded
    )
    token = "duplicate-device-document-asset-token-01"
    async with factory() as session:
        session.add(
            UploadAsset(
                asset_token=token,
                user_id=manager.id,
                college_id=college.id,
                original_name="existing.pdf",
                content_type="application/pdf",
                size_bytes=6,
                storage_path=str(tmp_path / "existing.pdf"),
            )
        )
        await session.commit()

    monkeypatch.setattr(documents_api.secrets, "token_urlsafe", lambda _size: token)
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(factory, actor, tmp_path, raise_app_exceptions=False) as client:
        response = await client.post(
            f"/api/v2/devices/{device.id}/documents",
            data=_form(),
            files={"file": ("collision.pdf", b"%PDF-1", "application/pdf")},
        )

    assert response.status_code == 500
    assert not (tmp_path / f"{token}.pdf").exists()
