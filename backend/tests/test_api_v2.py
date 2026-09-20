from datetime import date, timedelta

import pytest
from app.auth.security import hash_password
from app.core.settings import Settings
from app.infrastructure.db.models import College, Device, Role, User
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_v2_auth_device_and_reservation_api(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        college = College(code="API", name="API 测试学院")
        role = Role(role_code="STUDENT", role_name="学生")
        user = User(
            username="api-student",
            password_hash=hash_password("password-123"),
            real_name="接口学生",
            college=college,
            roles=[role],
            status=1,
        )
        device = Device(name="API 工作站", college=college, status="IDLE")
        session.add_all([college, role, user, device])
        await session.commit()

    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        cors_origins=[],
        enable_workers=False,
    )
    app = create_app(settings)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": "api-student", "password": "password-123"},
        )
        assert login.status_code == 200
        token = login.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        devices = await client.get("/api/v2/devices", headers=headers)
        assert devices.status_code == 200
        assert devices.json()["data"]["items"][0]["name"] == "API 工作站"

        recommendations = await client.get("/api/v2/recommendations", headers=headers)
        assert recommendations.status_code == 200
        assert recommendations.json()["data"][0]["device_id"] == device.id

        target = date.today() + timedelta(days=5)
        payload = {
            "device_id": device.id,
            "start_date": target.isoformat(),
            "end_date": target.isoformat(),
            "purpose": "API 并发链路",
        }
        created = await client.post(
            "/api/v2/reservations",
            json=payload,
            headers={**headers, "Idempotency-Key": "api-reservation-001"},
        )
        assert created.status_code == 201
        replay = await client.post(
            "/api/v2/reservations",
            json=payload,
            headers={**headers, "Idempotency-Key": "api-reservation-001"},
        )
        assert replay.status_code == 201
        assert (
            replay.json()["data"]["created"][0]["id"] == created.json()["data"]["created"][0]["id"]
        )

    app.dependency_overrides.clear()
