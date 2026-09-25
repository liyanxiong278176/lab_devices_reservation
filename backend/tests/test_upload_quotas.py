from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core.errors import ApiError
from app.core.settings import Settings
from app.core.uploads import cleanup_orphan_uploads, upload_quota_guard
from app.infrastructure.db.models import KnowledgeDocument, RepairReport, UploadAsset
from app.main import create_app
from starlette.requests import Request


def upload_request(app):
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "method": "POST",
            "path": "/api/v2/repair-uploads",
            "raw_path": b"/api/v2/repair-uploads",
            "query_string": b"",
            "headers": [],
            "app": app,
            "state": {},
        }
    )


@pytest.mark.asyncio
async def test_upload_quotas_bound_per_user_and_total_storage(seeded, tmp_path: Path) -> None:
    factory, college, _, user, _, _, _, _ = seeded
    app = create_app(
        Settings(
            environment="test",
            enable_workers=False,
            upload_user_quota_bytes=5,
            upload_college_quota_bytes=6,
            upload_total_quota_bytes=12,
        )
    )
    async with factory() as session:
        session.add(
            UploadAsset(
                asset_token="quota-used-asset",
                user_id=user.id,
                college_id=college.id,
                original_name="used.png",
                content_type="image/png",
                size_bytes=4,
                storage_path=str(tmp_path / "used.png"),
            )
        )
        await session.commit()
        async with upload_quota_guard(
            upload_request(app),
            session,
            user_id=user.id,
            college_id=college.id,
            incoming_bytes=1,
        ):
            session.add(
                UploadAsset(
                    asset_token="quota-added-asset",
                    user_id=user.id,
                    college_id=college.id,
                    original_name="added.png",
                    content_type="image/png",
                    size_bytes=1,
                    storage_path=str(tmp_path / "added.png"),
                )
            )
            await session.commit()
        with pytest.raises(ApiError) as per_user_error:
            async with upload_quota_guard(
                upload_request(app),
                session,
                user_id=user.id,
                college_id=college.id,
                incoming_bytes=1,
            ):
                pass
        assert per_user_error.value.code == "UPLOAD_USER_QUOTA_EXCEEDED"

        with pytest.raises(ApiError) as college_error:
            async with upload_quota_guard(
                upload_request(app),
                session,
                user_id=99999,
                college_id=college.id,
                incoming_bytes=2,
            ):
                pass
        assert college_error.value.code == "UPLOAD_COLLEGE_QUOTA_EXCEEDED"

        global_app = create_app(
            Settings(
                environment="test",
                enable_workers=False,
                upload_user_quota_bytes=20,
                upload_college_quota_bytes=20,
                upload_total_quota_bytes=12,
            )
        )
        with pytest.raises(ApiError) as total_error:
            async with upload_quota_guard(
                upload_request(global_app),
                session,
                user_id=99998,
                college_id=99998,
                incoming_bytes=8,
            ):
                pass
        assert total_error.value.code == "UPLOAD_STORAGE_FULL"


@pytest.mark.asyncio
async def test_ai_knowledge_storage_quota_is_cumulative_by_global_and_college_scope(
    seeded,
    tmp_path: Path,
) -> None:
    factory, college, _, user, _, _, _, _ = seeded
    upload_dir = tmp_path / "uploads"
    knowledge_dir = upload_dir / "ai-knowledge"
    knowledge_dir.mkdir(parents=True)
    existing_path = knowledge_dir / "existing.pdf"
    existing_path.write_bytes(b"0123456789")
    async with factory() as session:
        session.add(
            KnowledgeDocument(
                college_id=college.id,
                title="已有知识文件",
                source_type="SOP",
                body="",
                version=1,
                status="DRAFT",
                created_by=user.id,
                checksum="b" * 64,
                source_file_path=str(existing_path),
                source_file_name="existing.pdf",
                source_sha256="b" * 64,
                parse_status="UPLOADED",
            )
        )
        await session.commit()

        global_app = create_app(
            Settings(
                environment="test",
                enable_workers=False,
                upload_dir=str(upload_dir),
                ai_knowledge_global_storage_bytes=12,
                ai_knowledge_college_storage_bytes=20,
            )
        )
        with pytest.raises(ApiError) as global_error:
            async with upload_quota_guard(
                upload_request(global_app),
                session,
                user_id=user.id,
                college_id=college.id,
                incoming_bytes=3,
                ai_knowledge_document=True,
            ):
                pass
        assert global_error.value.code == "AI_KNOWLEDGE_STORAGE_FULL"
        await session.rollback()

        college_app = create_app(
            Settings(
                environment="test",
                enable_workers=False,
                upload_dir=str(upload_dir),
                ai_knowledge_global_storage_bytes=20,
                ai_knowledge_college_storage_bytes=10,
            )
        )
        with pytest.raises(ApiError) as college_error:
            async with upload_quota_guard(
                upload_request(college_app),
                session,
                user_id=user.id,
                college_id=college.id,
                incoming_bytes=1,
                ai_knowledge_document=True,
            ):
                pass
        assert college_error.value.code == "AI_KNOWLEDGE_COLLEGE_QUOTA_EXCEEDED"


@pytest.mark.asyncio
async def test_cleanup_removes_only_old_unreferenced_uploads(seeded, tmp_path: Path) -> None:
    factory, college, _, user, _, _, device, _ = seeded
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
    orphan_token = "orphan-upload-token-abcdefghijkl"
    referenced_token = "referenced-upload-token-abcdefgh"
    orphan_path = tmp_path / "orphan.png"
    referenced_path = tmp_path / "referenced.png"
    knowledge_path = tmp_path / "knowledge.png"
    orphan_path.write_bytes(b"orphan")
    referenced_path.write_bytes(b"referenced")
    knowledge_path.write_bytes(b"knowledge")

    async with factory() as session:
        session.add_all(
            [
                UploadAsset(
                    asset_token=orphan_token,
                    user_id=user.id,
                    college_id=college.id,
                    original_name="orphan.png",
                    content_type="image/png",
                    size_bytes=6,
                    storage_path=str(orphan_path),
                    created_at=old,
                ),
                UploadAsset(
                    asset_token=referenced_token,
                    user_id=user.id,
                    college_id=college.id,
                    original_name="referenced.png",
                    content_type="image/png",
                    size_bytes=10,
                    storage_path=str(referenced_path),
                    created_at=old,
                ),
                UploadAsset(
                    asset_token="ai-knowledge-upload-token-00000001",
                    user_id=user.id,
                    college_id=college.id,
                    original_name="knowledge.png",
                    content_type="image/png",
                    size_bytes=9,
                    storage_path=str(knowledge_path),
                    created_at=old,
                ),
            ]
        )
        await session.flush()
        session.add(
            RepairReport(
                college_id=college.id,
                device_id=device.id,
                reporter_id=user.id,
                title="保留附件引用",
                image_urls=[f"/api/v2/repair-uploads/{referenced_token}"],
                status="PENDING",
            )
        )
        session.add(
            KnowledgeDocument(
                college_id=college.id,
                title="保留知识库原件",
                source_type="SOP",
                body="",
                version=1,
                status="DRAFT",
                created_by=user.id,
                checksum="a" * 64,
                source_file_path=str(knowledge_path),
                source_file_name="knowledge.png",
                source_sha256="a" * 64,
                parse_status="UPLOADED",
            )
        )
        await session.commit()

        removed = await cleanup_orphan_uploads(session, str(tmp_path), retention_hours=24)
        assert removed == 1

    assert not orphan_path.exists()
    assert referenced_path.exists()
    assert knowledge_path.exists()


@pytest.mark.asyncio
async def test_cleanup_batch_skips_referenced_assets_to_reach_later_orphans(
    seeded, tmp_path: Path
) -> None:
    factory, college, _, user, _, _, device, _ = seeded
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
    referenced_tokens = [f"referenced-batch-token-{index:04d}" for index in range(12)]
    orphan_token = "orphan-after-referenced-batch-token"
    orphan_path = tmp_path / "later-orphan.png"
    orphan_path.write_bytes(b"orphan")

    async with factory() as session:
        session.add_all(
            [
                UploadAsset(
                    asset_token=token,
                    user_id=user.id,
                    college_id=college.id,
                    original_name=f"{token}.png",
                    content_type="image/png",
                    size_bytes=1,
                    storage_path=str(tmp_path / f"{token}.png"),
                    created_at=old,
                )
                for token in referenced_tokens
            ]
            + [
                UploadAsset(
                    asset_token=orphan_token,
                    user_id=user.id,
                    college_id=college.id,
                    original_name="later-orphan.png",
                    content_type="image/png",
                    size_bytes=6,
                    storage_path=str(orphan_path),
                    created_at=old,
                )
            ]
        )
        session.add(
            RepairReport(
                college_id=college.id,
                device_id=device.id,
                reporter_id=user.id,
                title="批量引用附件保留",
                image_urls=[f"/api/v2/repair-uploads/{token}" for token in referenced_tokens],
                status="PENDING",
            )
        )
        await session.commit()

        removed = await cleanup_orphan_uploads(
            session, str(tmp_path), retention_hours=24, batch_size=5
        )
        assert removed == 1

    assert not orphan_path.exists()
