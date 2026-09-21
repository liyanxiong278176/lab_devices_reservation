from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.db.models import Reservation, ReservationItem
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_repair_upload_is_validated_and_college_scoped(seeded, tmp_path: Path) -> None:
    factory, college, other_college, student1, student2, _, _, _ = seeded
    app = create_app(
        Settings(
            environment="test",
            cors_origins=[],
            enable_workers=False,
            rate_limit_enabled=False,
            upload_dir=str(tmp_path),
        )
    )
    current = Principal(
        user_id=student1.id,
        username=student1.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="upload-test",
    )

    async def override_db():
        async with factory() as session:
            yield session

    async def override_principal() -> Principal:
        return current

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            valid_png = b"\x89PNG\r\n\x1a\n" + b"safe-test"
            response = await client.post(
                "/api/v2/repair-uploads",
                files={"file": ("fault.png", valid_png, "image/png")},
            )
            assert response.status_code == 201
            payload = response.json()["data"]
            stored = tmp_path / next(path.name for path in tmp_path.iterdir())
            assert stored.is_file()
            assert payload["content_type"] == "image/png"

            fetched = await client.get(payload["url"])
            assert fetched.status_code == 200
            assert fetched.content == valid_png

            current = Principal(
                user_id=student2.id,
                username=student2.username,
                college_id=other_college.id,
                roles=("STUDENT",),
                token_type="access",
                token_id="upload-other-college",
            )
            forbidden = await client.get(payload["url"])
            assert forbidden.status_code == 404

            invalid = await client.post(
                "/api/v2/repair-uploads",
                files={"file": ("fault.txt", b"text", "text/plain")},
            )
            assert invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_completed_reservation_has_one_college_scoped_feedback(seeded) -> None:
    factory, college, other_college, student1, student2, _, device, _ = seeded
    from datetime import date, timedelta

    target = date.today() + timedelta(days=2)
    async with factory() as session:
        reservation = Reservation(
            college_id=college.id,
            user_id=student1.id,
            device_id=device.id,
            purpose="反馈测试",
            start_date=target,
            end_date=target,
            slot_count=1,
            status="COMPLETED",
        )
        reservation.days = [ReservationItem(device_id=device.id, reservation_date=target)]
        session.add(reservation)
        await session.commit()
        reservation_id = reservation.id

    app = create_app(
        Settings(
            environment="test",
            cors_origins=[],
            enable_workers=False,
            rate_limit_enabled=False,
        )
    )
    current = Principal(
        user_id=student1.id,
        username=student1.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="feedback-test",
    )

    async def override_db():
        async with factory() as session:
            yield session

    async def override_principal() -> Principal:
        return current

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                f"/api/v2/reservations/{reservation_id}/feedback",
                json={"rating": 4, "comment": "设备状态良好"},
            )
            assert created.status_code == 201
            assert created.json()["data"]["rating"] == 4

            loaded = await client.get(f"/api/v2/reservations/{reservation_id}/feedback")
            assert loaded.status_code == 200
            assert loaded.json()["data"]["comment"] == "设备状态良好"

            duplicate = await client.post(
                f"/api/v2/reservations/{reservation_id}/feedback",
                json={"rating": 5},
            )
            assert duplicate.status_code == 409

            current = Principal(
                user_id=student2.id,
                username=student2.username,
                college_id=other_college.id,
                roles=("STUDENT",),
                token_type="access",
                token_id="feedback-other-college",
            )
            forbidden = await client.get(f"/api/v2/reservations/{reservation_id}/feedback")
            assert forbidden.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_device_documents_and_blackouts_are_validated_and_scoped(
    seeded, tmp_path: Path
) -> None:
    factory, college, other_college, student1, student2, manager, device, _ = seeded
    app = create_app(
        Settings(
            environment="test",
            cors_origins=[],
            enable_workers=False,
            rate_limit_enabled=False,
            upload_dir=str(tmp_path),
        )
    )
    current = Principal(
        user_id=manager.id,
        username=manager.username,
        college_id=college.id,
        roles=("LAB_ADMIN",),
        token_type="access",
        token_id="document-manager",
    )

    async def override_db():
        async with factory() as session:
            yield session

    async def override_principal() -> Principal:
        return current

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal
    target = (date.today() + timedelta(days=7)).isoformat()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            pdf = b"%PDF-1.7\nminimal test document"
            created = await client.post(
                f"/api/v2/devices/{device.id}/documents",
                data={"document_type": "SOP", "title": "设备操作规程"},
                files={"file": ("sop.pdf", pdf, "application/pdf")},
            )
            assert created.status_code == 201
            document = created.json()["data"]
            assert document["document_type"] == "SOP"

            listed = await client.get(f"/api/v2/devices/{device.id}/documents")
            assert listed.status_code == 200
            assert listed.json()["data"][0]["title"] == "设备操作规程"

            blackout = await client.post(
                "/api/v2/blackouts",
                json={
                    "scope_type": "DEVICE",
                    "scope_id": device.id,
                    "blocked_date": target,
                    "reason": "年度检修",
                },
            )
            assert blackout.status_code == 201

            current = Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=college.id,
                roles=("STUDENT",),
                token_type="access",
                token_id="document-student",
            )
            availability = await client.get(
                f"/api/v2/devices/{device.id}/availability",
                params={"start_date": target, "end_date": target},
            )
            assert availability.status_code == 200
            assert availability.json()["data"][0]["status"] == "BLACKOUT"

            current = Principal(
                user_id=student2.id,
                username=student2.username,
                college_id=other_college.id,
                roles=("STUDENT",),
                token_type="access",
                token_id="document-other-college",
            )
            forbidden = await client.get(f"/api/v2/devices/{device.id}/documents")
            assert forbidden.status_code == 404
    finally:
        app.dependency_overrides.clear()
