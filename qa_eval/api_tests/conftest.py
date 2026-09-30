from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qa_eval"))
sys.path.insert(0, str(ROOT / "backend"))

from app.infrastructure.db import models  # noqa: E402
from config import BASE_URL, FIXTURE_FILE, require_mysql_dsn  # noqa: E402


@dataclass
class SessionClient:
    client: AsyncClient
    username: str
    user_id: int
    csrf: str
    login_response: Any
    password: str

    def headers(
        self, *, csrf: str | None = None, origin: str = "http://127.0.0.1:5173"
    ) -> dict[str, str]:
        result = {"Origin": origin}
        if csrf is not None:
            result["X-CSRF-Token"] = csrf
        else:
            result["X-CSRF-Token"] = self.csrf
        return result


@pytest.fixture(scope="session")
def manifest() -> dict[str, Any]:
    path = FIXTURE_FILE if FIXTURE_FILE.is_absolute() else ROOT / FIXTURE_FILE
    if not path.exists():
        pytest.fail("QA fixture missing; run qa_eval/seed_factory.py create first")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest_asyncio.fixture
async def client_factory(manifest: dict[str, Any]):
    clients: list[SessionClient] = []
    indexes = {"CSE": 0, "BIO": 0}
    password = manifest["password"]

    async def login(role: str = "student", college: str = "CSE") -> SessionClient:
        if role == "student":
            accounts = manifest["accounts"]["students"][college]
            index = indexes[college] % len(accounts)
            indexes[college] += 1
            account = accounts[index]
        elif role == "manager":
            account = manifest["accounts"]["managers"][college]
        elif role == "admin":
            account = manifest["accounts"]["admin"]
        elif role == "sse":
            account = manifest["accounts"]["sse"]
        else:
            raise ValueError(f"Unknown QA persona: {role}")

        client = AsyncClient(base_url=BASE_URL, timeout=20)
        csrf_response = await client.get("/api/v2/auth/csrf")
        assert csrf_response.status_code == 200, csrf_response.text
        csrf = csrf_response.json()["data"]["csrf_token"]
        response = await client.post(
            "/api/v2/auth/login",
            json={"username": account["username"], "password": password},
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, (
            f"login failed for QA persona {role}: {response.status_code}"
        )
        session = SessionClient(
            client=client,
            username=account["username"],
            user_id=int(account["user_id"]),
            csrf=response.json()["data"]["csrf_token"],
            login_response=response,
            password=password,
        )
        clients.append(session)
        return session

    yield login

    for session in clients:
        response = await session.client.post("/api/v2/auth/logout", headers=session.headers())
        assert response.status_code == 200, f"QA session cleanup failed: {response.status_code}"
        await session.client.aclose()


@pytest_asyncio.fixture
async def mysql_factory(manifest: dict[str, Any]):
    del manifest
    engine = create_async_engine(
        require_mysql_dsn(), pool_pre_ping=True, pool_size=3, max_overflow=2
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def occupied_day_count(factory: async_sessionmaker[AsyncSession], device_id: int, day) -> int:
    from sqlalchemy import func, select

    async with factory() as session:
        return int(
            await session.scalar(
                select(func.count(models.ReservationItem.id)).where(
                    models.ReservationItem.device_id == device_id,
                    models.ReservationItem.reservation_date == day,
                )
            )
            or 0
        )
