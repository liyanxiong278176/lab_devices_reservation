from __future__ import annotations

import json
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
import jwt
from app.infrastructure.db.models import User
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "qa_system"


def _ids() -> dict[str, object]:
    return json.loads((QA / "results" / "seed_ids.json").read_text(encoding="utf-8"))


def test_unauthenticated_business_and_ai_reads_fail_closed(sync_client) -> None:
    assert sync_client.get("/devices").status_code == 401
    assert sync_client.get("/ai/status").status_code == 401


async def test_session_cookie_claims_refresh_rotation_and_replay(client_factory, qa_state) -> None:
    credentials = json.loads((QA / "results" / "accounts.local.json").read_text(encoding="utf-8"))[
        "student_a"
    ]
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000/api/v2", timeout=20) as client:
        csrf = (await client.get("/auth/csrf")).json()["data"]["csrf_token"]
        login = await client.post(
            "/auth/login",
            json=credentials,
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
        )
        assert login.status_code == 200
        cookie = SimpleCookie()
        for line in login.headers.get_list("set-cookie"):
            cookie.load(line)
        access = cookie["lab_access"]
        refresh = cookie["lab_refresh"]
        assert access["httponly"] is True
        assert access["samesite"].lower() in {"lax", "strict"}
        claims = jwt.decode(access.value, options={"verify_signature": False, "verify_exp": False})
        assert set(claims) == {"sid", "type", "jti", "iss", "aud", "iat", "exp"}
        assert claims["type"] == "access"
        assert len(claims["sid"]) >= 43
        old_refresh = refresh.value

        refreshed = await client.get("/auth/csrf")
        rotated = await client.post(
            "/auth/refresh",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "X-CSRF-Token": refreshed.json()["data"]["csrf_token"],
            },
        )
        assert rotated.status_code == 200
        new_refresh = client.cookies.get("lab_refresh")
        assert new_refresh and new_refresh != old_refresh

        client.cookies.set("lab_refresh", old_refresh)
        csrf_again = await client.get("/auth/csrf")
        replay = await client.post(
            "/auth/refresh",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "X-CSRF-Token": csrf_again.json()["data"]["csrf_token"],
            },
        )
        assert replay.status_code == 401


async def test_cross_college_device_direct_id_and_list_are_hidden(client_factory) -> None:
    ids = _ids()
    device_b = int(ids["device"][1])
    client = await client_factory("student_a")
    try:
        detail = await client.get(f"/devices/{device_b}")
        assert detail.status_code in {403, 404}
        listing = await client.get("/devices", params={"page": 1, "page_size": 100})
        assert listing.status_code == 200
        body = listing.json()
        encoded = json.dumps(body, ensure_ascii=False)
        assert "QAEVAL_" in encoded
        assert "direct device" not in encoded
    finally:
        await client.aclose()


async def test_disabled_account_invalidates_business_and_ai_access(
    client_factory, qa_state
) -> None:
    client = await client_factory("student_a")
    try:
        whoami = await client.get("/auth/me")
        user_id = int(whoami.json()["data"]["id"])
        engine = create_async_engine(str(qa_state["mysql_dsn"]), pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory.begin() as session:
                await session.execute(update(User).where(User.id == user_id).values(status=0))
            business = await client.get("/devices")
            ai = await client.get("/ai/status")
            assert business.status_code == 401
            assert ai.status_code == 401
        finally:
            async with factory.begin() as session:
                await session.execute(update(User).where(User.id == user_id).values(status=1))
            await engine.dispose()
    finally:
        await client.aclose()


async def test_redis_unavailable_fails_closed_for_business_and_ai(client_factory, qa_state) -> None:
    import subprocess
    import time

    admin_access_name = "lab_access"
    normal_client = await client_factory("student_a")
    try:
        access = normal_client.cookies.get(admin_access_name)
        assert access
        process = subprocess.Popen(
            [
                str(QA / ".venv" / "Scripts" / "python.exe"),
                str(QA / "run_isolated_api.py"),
                "--redis-fail-closed",
            ],
            cwd=ROOT,
            stdout=(QA / "results" / "redis-fail-closed.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            ready = False
            with httpx.Client(timeout=1) as probe:
                while time.monotonic() < deadline:
                    try:
                        if probe.get("http://127.0.0.1:8001/api/v2/live").status_code == 200:
                            ready = True
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
            assert ready, "fail-closed probe server did not become ready"
            async with httpx.AsyncClient(timeout=5, cookies={admin_access_name: access}) as probe:
                business = await probe.get("http://127.0.0.1:8001/api/v2/devices")
                ai = await probe.get("http://127.0.0.1:8001/api/v2/ai/status")
            assert business.status_code == 503
            assert ai.status_code == 503
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    finally:
        await normal_client.aclose()
