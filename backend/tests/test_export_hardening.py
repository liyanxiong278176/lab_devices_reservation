from __future__ import annotations

import pytest
from app.application.exports import export_rows, managed_device_ids, safe_csv_row, scope_fingerprint
from app.auth.security import Principal, get_current_principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import Device, ExportTask, Lab
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from starlette.requests import Request


def test_csv_formula_prefix_is_neutralized_but_numbers_are_preserved() -> None:
    safe = safe_csv_row(
        {
            "name": '  =HYPERLINK("https://evil.invalid")',
            "phone": "\t+cmd|' /C calc'!A0",
            "normal": "普通用途",
            "amount": -12,
        }
    )
    assert safe["name"].startswith("'")
    assert safe["phone"].startswith("'")
    assert safe["normal"] == "普通用途"
    assert safe["amount"] == -12


def manager_principal(manager, college_id: int) -> Principal:
    return Principal(
        user_id=manager.id,
        username=manager.username,
        college_id=college_id,
        roles=("LAB_ADMIN",),
        token_type="access",
        token_id="export-test",
    )


def request_for(app) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "method": "GET",
            "path": "/api/v2/reports",
            "raw_path": b"/api/v2/reports",
            "query_string": b"",
            "headers": [],
            "app": app,
            "state": {},
        }
    )


@pytest.mark.asyncio
async def test_export_download_is_denied_after_manager_scope_is_revoked(seeded) -> None:
    factory, college, _, _, _, manager, device, _ = seeded
    principal = manager_principal(manager, college.id)
    async with factory() as session:
        device_ids, scope = await managed_device_ids(session, principal)
        task = ExportTask(
            requester_id=manager.id,
            college_id=college.id,
            export_type="devices",
            filters={
                "college_id": None,
                "_scope_fingerprint": scope_fingerprint(device_ids, scope),
            },
            status="PENDING",
        )
        session.add(task)
        await session.commit()
        task_id = task.id
        assert device.id in device_ids

    async with factory() as session:
        await session.execute(update(Lab).where(Lab.id == device.lab_id).values(manager_id=None))
        await session.commit()

    app = create_app(Settings(environment="test", enable_workers=False))
    from app.api.v2.reports import _load_task

    async with factory() as session:
        with pytest.raises(ApiError) as error:
            await _load_task(task_id, request_for(app), principal, session)
        assert getattr(error.value, "code", None) == "EXPORT_NOT_FOUND"


@pytest.mark.asyncio
async def test_direct_export_caps_rows_before_building_response(seeded) -> None:
    factory, college, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        for index in range(2):
            session.add(
                Device(
                    name=f"导出测试设备-{index}",
                    college_id=college.id,
                    lab_id=device.lab_id,
                    status="IDLE",
                )
            )
        await session.commit()

    app = create_app(
        Settings(
            environment="test",
            enable_workers=False,
            rate_limit_enabled=False,
            export_sync_row_limit=2,
        )
    )
    principal = manager_principal(manager, college.id)

    async def override_db():
        async with factory() as session:
            yield session

    async def override_principal() -> Principal:
        return principal

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v2/reports/export/devices")
        assert response.status_code == 413
        assert response.json()["data"]["minimum_row_count"] == 3
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_row_iterator_supports_bounded_reads(seeded) -> None:
    factory, college, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        for index in range(4):
            session.add(
                Device(
                    name=f"分页导出设备-{index}",
                    college_id=college.id,
                    lab_id=device.lab_id,
                    status="IDLE",
                )
            )
        await session.commit()

    async with factory() as session:
        rows = await export_rows(
            session,
            manager_principal(manager, college.id),
            "devices",
            max_rows=3,
        )
        assert len(rows) == 3
