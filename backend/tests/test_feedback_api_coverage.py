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
from app.infrastructure.db.models import Reservation, ReservationItem
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(
    user_id: int, college_id: int | None, *roles: str, permissions: tuple[str, ...] = ()
) -> Principal:
    return Principal(
        user_id=user_id,
        username=f"feedback-{user_id}",
        college_id=college_id,
        roles=roles,
        token_type="access",
        token_id=f"feedback-coverage-{user_id}",
        permissions=permissions,
    )


@asynccontextmanager
async def _client(
    factory: async_sessionmaker[AsyncSession], actor: dict[str, Principal], tmp_path: Path
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(
            environment="test",
            mysql_dsn="sqlite+aiosqlite:///:memory:",
            cors_origins=["http://test"],
            redis_url="redis://127.0.0.1:6379/15",
            enable_workers=False,
            rate_limit_enabled=False,
            upload_dir=str(tmp_path),
        )
    )

    async def override_db():
        async with factory() as session:
            yield session

    async def override_actor() -> Principal:
        return actor["value"]

    async def noop() -> None:
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_actor
    app.dependency_overrides[enforce_csrf] = noop
    app.dependency_overrides[enforce_authenticated_rate_limit] = noop
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_feedback_write_eligibility_duplicate_and_read_scope(seeded, tmp_path: Path) -> None:
    factory, college, other_college, student, other_student, manager, device, other_device = seeded
    completed_day = date.today() - timedelta(days=5)
    pending_day = date.today() + timedelta(days=5)
    foreign_day = date.today() - timedelta(days=7)
    async with factory() as session:
        completed = Reservation(
            college_id=college.id,
            user_id=student.id,
            device_id=device.id,
            purpose="completed feedback reservation",
            start_date=completed_day,
            end_date=completed_day,
            slot_count=1,
            status="COMPLETED",
        )
        completed.days = [ReservationItem(device_id=device.id, reservation_date=completed_day)]
        pending = Reservation(
            college_id=college.id,
            user_id=student.id,
            device_id=device.id,
            purpose="pending feedback reservation",
            start_date=pending_day,
            end_date=pending_day,
            slot_count=1,
            status="PENDING",
        )
        pending.days = [ReservationItem(device_id=device.id, reservation_date=pending_day)]
        foreign = Reservation(
            college_id=other_college.id,
            user_id=other_student.id,
            device_id=other_device.id,
            purpose="foreign completed feedback reservation",
            start_date=foreign_day,
            end_date=foreign_day,
            slot_count=1,
            status="COMPLETED",
        )
        foreign.days = [ReservationItem(device_id=other_device.id, reservation_date=foreign_day)]
        session.add_all([completed, pending, foreign])
        await session.commit()
        completed_id, pending_id, foreign_id = completed.id, pending.id, foreign.id

    student_actor = _principal(
        student.id,
        college.id,
        "STUDENT",
        permissions=("feedback:create", "feedback:read:own"),
    )
    actor = {"value": _principal(student.id, college.id, "STUDENT", permissions=())}
    async with _client(factory, actor, tmp_path) as client:
        no_permission = await client.post(
            f"/api/v2/reservations/{completed_id}/feedback", json={"rating": 4}
        )
        assert no_permission.status_code == 403

        actor["value"] = _principal(student.id, college.id, "STUDENT", permissions=())
        missing = await client.post("/api/v2/reservations/999999/feedback", json={"rating": 4})
        assert missing.status_code == 403
        actor["value"] = student_actor
        missing = await client.post("/api/v2/reservations/999999/feedback", json={"rating": 4})
        assert missing.status_code == 404

        actor["value"] = _principal(
            other_student.id, other_college.id, "STUDENT", permissions=("feedback:create",)
        )
        other_owner = await client.post(
            f"/api/v2/reservations/{completed_id}/feedback", json={"rating": 4}
        )
        assert other_owner.status_code == 403

        actor["value"] = student_actor
        not_ready = await client.post(
            f"/api/v2/reservations/{pending_id}/feedback", json={"rating": 4}
        )
        assert not_ready.status_code == 409

        created = await client.post(
            f"/api/v2/reservations/{completed_id}/feedback",
            json={"rating": 5, "comment": None},
        )
        assert created.status_code == 201
        assert created.json()["data"]["comment"] is None
        duplicate = await client.post(
            f"/api/v2/reservations/{completed_id}/feedback", json={"rating": 3}
        )
        assert duplicate.status_code == 409

        own = await client.get(f"/api/v2/reservations/{completed_id}/feedback")
        assert own.status_code == 200
        assert own.json()["data"]["rating"] == 5
        no_feedback = await client.get(f"/api/v2/reservations/{pending_id}/feedback")
        assert no_feedback.status_code == 200
        assert no_feedback.json()["data"] is None

        actor["value"] = _principal(student.id, college.id, "STUDENT", permissions=())
        no_read_permission = await client.get(f"/api/v2/reservations/{completed_id}/feedback")
        assert no_read_permission.status_code == 404

        actor["value"] = _principal(
            student.id, other_college.id, "STUDENT", permissions=("feedback:read:own",)
        )
        wrong_tenant = await client.get(f"/api/v2/reservations/{completed_id}/feedback")
        assert wrong_tenant.status_code == 404

        actor["value"] = _principal(
            other_student.id, other_college.id, "STUDENT", permissions=("feedback:read:scope",)
        )
        wrong_manager_scope = await client.get(f"/api/v2/reservations/{completed_id}/feedback")
        assert wrong_manager_scope.status_code == 404

        actor["value"] = _principal(
            manager.id, college.id, "LAB_ADMIN", permissions=("feedback:read:scope",)
        )
        manager_read = await client.get(f"/api/v2/reservations/{completed_id}/feedback")
        assert manager_read.status_code == 200

        actor["value"] = _principal(manager.id, None, "SYS_ADMIN")
        system_admin_read = await client.get(f"/api/v2/reservations/{foreign_id}/feedback")
        assert system_admin_read.status_code == 200
