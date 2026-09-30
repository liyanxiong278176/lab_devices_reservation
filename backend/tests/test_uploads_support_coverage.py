from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.errors import ApiError
from app.core.uploads import (
    _contains_upload_token,
    _ensure_upload_quota_bucket,
    _lock_upload_quota_buckets,
    _quota_scopes,
    _upload_is_referenced,
    cleanup_orphan_uploads,
    upload_cleanup_loop,
)
from app.infrastructure.db.models import DeviceHandover, UploadAsset
from sqlalchemy import literal, select
from sqlalchemy.dialects.mysql import dialect as mysql_dialect


def test_upload_reference_predicates_use_binary_collation_and_optional_knowledge_path() -> None:
    token_search = _contains_upload_token(
        DeviceHandover.handover_image_urls,
        literal("opaque-token"),
        mysql=True,
    )
    compiled = str(token_search.compile(dialect=mysql_dialect()))
    assert "utf8mb4_bin" in compiled

    predicate = _upload_is_referenced(1, "opaque-token", None, mysql=True)
    sql = str(predicate.compile(dialect=mysql_dialect()))
    assert "v2_device_handover" in sql
    assert "v2_knowledge_document" not in sql
    assert _quota_scopes(7, None) == [("global", 0), ("user", 7)]
    assert _quota_scopes(7, 3) == [("global", 0), ("college", 3), ("user", 7)]


@pytest.mark.asyncio
async def test_unknown_database_quota_adapter_fails_closed_when_bucket_is_missing() -> None:
    class Session:
        def __init__(self) -> None:
            self.values = deque([12, None, None])
            self.added: list[object] = []
            self.flushed = 0

        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def scalar(self, *_args: object, **_kwargs: object) -> object:
            return self.values.popleft()

        def add(self, value: object) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            self.flushed += 1

    session = Session()
    with pytest.raises(ApiError) as error:
        await _lock_upload_quota_buckets(session, [("global", 0)])  # type: ignore[arg-type]

    assert error.value.code == "UPLOAD_QUOTA_UNAVAILABLE"
    assert len(session.added) == 1
    assert session.flushed == 1


@pytest.mark.asyncio
async def test_unknown_database_quota_adapter_reuses_existing_bucket() -> None:
    class Session:
        def __init__(self) -> None:
            self.values = deque([12, 42, SimpleNamespace(used_bytes=12)])
            self.added: list[object] = []

        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def scalar(self, *_args: object, **_kwargs: object) -> object:
            return self.values.popleft()

        def add(self, value: object) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            raise AssertionError("existing bucket must not be inserted")

    session = Session()
    buckets = await _lock_upload_quota_buckets(session, [("global", 0)])  # type: ignore[arg-type]
    assert buckets[("global", 0)].used_bytes == 12
    assert session.added == []


@pytest.mark.asyncio
async def test_mysql_quota_bucket_initialization_uses_atomic_upsert() -> None:
    class Session:
        executed: object | None = None

        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

        async def scalar(self, *_args: object, **_kwargs: object) -> int:
            return 18

        async def execute(self, statement: object) -> None:
            self.executed = statement

    session = Session()
    await _ensure_upload_quota_bucket(session, "global", 0)  # type: ignore[arg-type]

    assert session.executed is not None
    assert "ON DUPLICATE KEY UPDATE" in str(session.executed.compile(dialect=mysql_dialect()))


@pytest.mark.asyncio
async def test_orphan_cleanup_skips_concurrently_missing_and_referenced_assets(
    seeded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    factory, college, _, user, *_ = seeded
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
    original_scalar = AsyncSession.scalar

    for mode, token in (
        ("missing", "cleanup-race-missing-asset"),
        ("maintenance", "cleanup-race-maintenance-ref"),
        ("referenced", "cleanup-race-business-ref"),
    ):
        async with factory() as session:
            session.add(
                UploadAsset(
                    asset_token=token,
                    user_id=user.id,
                    college_id=college.id,
                    original_name=f"{token}.png",
                    content_type="image/png",
                    size_bytes=3,
                    storage_path=str(tmp_path / f"{token}.png"),
                    created_at=old,
                )
            )
            await session.commit()

            scalar_calls = 0

            async def raced_scalar(
                current_session: AsyncSession,
                statement: object,
                *args: object,
                **kwargs: object,
            ):
                nonlocal scalar_calls
                if current_session is session:
                    scalar_calls += 1
                    if mode == "missing":
                        return None
                    if mode == "maintenance" and scalar_calls % 2 == 0:
                        return 99
                    if mode == "referenced" and scalar_calls % 3 == 0:
                        return True
                return await original_scalar(current_session, statement, *args, **kwargs)

            monkeypatch.setattr(AsyncSession, "scalar", raced_scalar)
            assert await cleanup_orphan_uploads(session, str(tmp_path)) == 0, mode
            monkeypatch.setattr(AsyncSession, "scalar", original_scalar)

        async with factory() as session:
            stored_asset = await session.scalar(
                select(UploadAsset).where(UploadAsset.asset_token == token)
            )
            assert stored_asset is not None


@pytest.mark.asyncio
async def test_orphan_cleanup_keeps_assets_outside_the_private_upload_root(
    seeded, tmp_path: Path
) -> None:
    factory, college, _, user, *_ = seeded
    token = "cleanup-outside-root-token-0001"
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
    async with factory() as session:
        session.add(
            UploadAsset(
                asset_token=token,
                user_id=user.id,
                college_id=college.id,
                original_name="outside.png",
                content_type="image/png",
                size_bytes=4,
                storage_path=str(tmp_path.parent / "outside-upload.png"),
                created_at=old,
            )
        )
        await session.commit()

        removed = await cleanup_orphan_uploads(session, str(tmp_path))

    assert removed == 0
    async with factory() as session:
        retained = await session.scalar(select(UploadAsset).where(UploadAsset.asset_token == token))
    assert retained is not None


@pytest.mark.asyncio
async def test_orphan_cleanup_commits_metadata_when_file_removal_fails(
    seeded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import uploads

    factory, college, _, user, *_ = seeded
    token = "cleanup-unlink-failure-token-001"
    path = tmp_path / "unlink-failure.png"
    path.write_bytes(b"private image")
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
    async with factory() as session:
        session.add(
            UploadAsset(
                asset_token=token,
                user_id=user.id,
                college_id=college.id,
                original_name=path.name,
                content_type="image/png",
                size_bytes=13,
                storage_path=str(path),
                created_at=old,
            )
        )
        await session.commit()

        original_to_thread = uploads.asyncio.to_thread

        async def fail_unlink(function, *args: object, **kwargs: object):
            if getattr(function, "__name__", "") == "unlink":
                raise OSError("storage unavailable")
            return await original_to_thread(function, *args, **kwargs)

        monkeypatch.setattr(uploads.asyncio, "to_thread", fail_unlink)
        assert await cleanup_orphan_uploads(session, str(tmp_path)) == 1

    assert path.exists()
    async with factory() as session:
        removed = await session.scalar(select(UploadAsset).where(UploadAsset.asset_token == token))
    assert removed is None


@pytest.mark.asyncio
async def test_upload_cleanup_loop_handles_missing_factory_and_recovers_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import uploads

    no_factory_app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(upload_cleanup_interval_seconds=5, upload_dir="unused")
        )
    )

    async def cancel_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(uploads.asyncio, "sleep", cancel_sleep)
    with pytest.raises(asyncio.CancelledError):
        await upload_cleanup_loop(no_factory_app)  # type: ignore[arg-type]

    class SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(
                upload_cleanup_interval_seconds=1,
                upload_dir="configured-upload-dir",
                upload_orphan_retention_hours=12,
            ),
            session_factory=lambda: SessionContext(),
        )
    )
    calls: list[tuple[object, str, int]] = []

    async def failed_cleanup(session: object, upload_dir: str, *, retention_hours: int) -> int:
        calls.append((session, upload_dir, retention_hours))
        raise RuntimeError("transient janitor failure")

    monkeypatch.setattr(uploads, "cleanup_orphan_uploads", failed_cleanup)
    with pytest.raises(asyncio.CancelledError):
        await upload_cleanup_loop(app)  # type: ignore[arg-type]

    assert calls == [(calls[0][0], "configured-upload-dir", 12)]

    async def cancel_cleanup(*_args: object, **_kwargs: object) -> int:
        raise asyncio.CancelledError

    monkeypatch.setattr(uploads, "cleanup_orphan_uploads", cancel_cleanup)
    with pytest.raises(asyncio.CancelledError):
        await upload_cleanup_loop(app)  # type: ignore[arg-type]
