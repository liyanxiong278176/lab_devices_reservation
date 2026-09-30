from __future__ import annotations

import base64
import json

import pytest
from config import BASE_URL
from httpx import AsyncClient

from conftest import occupied_day_count


def _jwt_claims(token: str) -> dict[str, object]:
    segment = token.split(".")[1]
    segment += "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment.encode()))


@pytest.mark.asyncio
async def test_invalid_username_and_password_have_same_public_error(client_factory, manifest):
    account = manifest["accounts"]["students"]["CSE"][0]
    attempts = []
    for username, password in (
        ("qaeval-user-that-does-not-exist", manifest["password"]),
        (account["username"], "Definitely-Wrong-QA-Password-99!"),
    ):
        from config import BASE_URL
        from httpx import AsyncClient

        async with AsyncClient(base_url=BASE_URL, timeout=20) as client:
            csrf = (await client.get("/api/v2/auth/csrf")).json()["data"]["csrf_token"]
            response = await client.post(
                "/api/v2/auth/login",
                json={"username": username, "password": password},
                headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
            )
            attempts.append(
                (response.status_code, response.json().get("code"), response.json().get("message"))
            )
    assert attempts[0] == attempts[1]
    assert attempts[0][0:2] == (401, "INVALID_CREDENTIALS")


@pytest.mark.asyncio
async def test_cookie_claims_sid_entropy_and_login_rotation(client_factory):
    session = await client_factory("student", "CSE")
    cookies = session.login_response.headers.get_list("set-cookie")
    access = next(value for value in cookies if value.startswith("lab_access="))
    refresh = next(value for value in cookies if value.startswith("lab_refresh="))
    assert "httponly" in access.lower() and "samesite=lax" in access.lower()
    assert "httponly" in refresh.lower() and "samesite=lax" in refresh.lower()

    first_token = session.client.cookies.get("lab_access")
    first_claims = _jwt_claims(first_token)
    assert set(first_claims) == {"sid", "type", "jti", "iss", "aud", "iat", "exp"}
    first_sid = str(first_claims["sid"])
    assert len(first_sid) >= 40
    assert session.client.cookies.get("lab_refresh")

    logout = await session.client.post("/api/v2/auth/logout", headers=session.headers())
    assert logout.status_code == 200
    csrf = (await session.client.get("/api/v2/auth/csrf")).json()["data"]["csrf_token"]
    second_login = await session.client.post(
        "/api/v2/auth/login",
        json={"username": session.username, "password": session.password},
        headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
    )
    assert second_login.status_code == 200
    second_claims = _jwt_claims(session.client.cookies.get("lab_access"))
    assert second_claims["sid"] != first_sid
    session.csrf = second_login.json()["data"]["csrf_token"]
    session.login_response = second_login


@pytest.mark.asyncio
async def test_csrf_origin_and_session_cookie_are_enforced(client_factory):
    session = await client_factory("student", "CSE")
    path = "/api/v2/auth/logout"
    missing = await session.client.post(path, headers={"Origin": "http://127.0.0.1:5173"})
    wrong = await session.client.post(
        path,
        headers=session.headers(csrf="wrong-csrf-token"),
    )
    foreign = await client_factory("student", "CSE")
    cross_session = await session.client.post(path, headers=session.headers(csrf=foreign.csrf))
    untrusted_origin = await session.client.post(
        path,
        headers=session.headers(origin="https://attacker.invalid"),
    )
    assert [
        missing.status_code,
        wrong.status_code,
        cross_session.status_code,
        untrusted_origin.status_code,
    ] == [403] * 4
    assert (await session.client.get("/api/v2/auth/me")).status_code == 200

    from config import BASE_URL
    from httpx import AsyncClient

    async with AsyncClient(base_url=BASE_URL) as anonymous:
        no_cookie = await anonymous.post(
            path,
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": session.csrf},
        )
    assert no_cookie.status_code in (401, 403)


@pytest.mark.asyncio
async def test_student_cannot_read_or_reserve_foreign_college_device(
    client_factory, manifest, mysql_factory
):
    student = await client_factory("student", "CSE")
    foreign_device_id = manifest["device_ids"]["BIO"][1]
    detail = await student.client.get(f"/api/v2/devices/{foreign_device_id}")
    assert detail.status_code in (403, 404)

    from datetime import date, timedelta

    day = date.today() + timedelta(days=12)
    response = await student.client.post(
        "/api/v2/reservations",
        json={
            "device_id": foreign_device_id,
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "purpose": "跨学院越权预约验证",
        },
        headers=student.headers(),
    )
    assert response.status_code in (403, 404)
    assert await occupied_day_count(mysql_factory, foreign_device_id, day) == 0


@pytest.mark.asyncio
async def test_fifty_login_session_ids_are_unique_and_refresh_replay_revokes_session(manifest):
    """Integration/security: sample 50 real SIDs, rotate refresh, then replay the old token."""
    accounts = [
        *manifest["accounts"]["students"]["CSE"],
        *manifest["accounts"]["students"]["BIO"],
        *manifest["accounts"]["managers"].values(),
        manifest["accounts"]["admin"],
    ]
    opened: list[tuple[AsyncClient, str]] = []
    session_ids: list[str] = []
    refresh_victim: AsyncClient | None = None
    try:
        for index in range(50):
            account = accounts[index % len(accounts)]
            client = AsyncClient(base_url=BASE_URL, timeout=20)
            bootstrap = await client.get("/api/v2/auth/csrf")
            assert bootstrap.status_code == 200, bootstrap.text
            csrf = bootstrap.json()["data"]["csrf_token"]
            login = await client.post(
                "/api/v2/auth/login",
                json={"username": account["username"], "password": manifest["password"]},
                headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
            )
            assert login.status_code == 200, f"login sample {index + 1} failed: {login.status_code}"
            access_cookie = client.cookies.get("lab_access")
            assert access_cookie
            sid = str(_jwt_claims(access_cookie)["sid"])
            assert len(sid) >= 43
            session_ids.append(sid)
            opened.append((client, login.json()["data"]["csrf_token"]))

        assert len(session_ids) == 50
        assert len(set(session_ids)) == 50

        refresh_victim, csrf = opened[-1]
        previous_refresh = refresh_victim.cookies.get("lab_refresh")
        assert previous_refresh
        rotate = await refresh_victim.post(
            "/api/v2/auth/refresh",
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
        )
        assert rotate.status_code == 200, rotate.text
        rotated_refresh = refresh_victim.cookies.get("lab_refresh")
        assert rotated_refresh and rotated_refresh != previous_refresh

        replay_client = AsyncClient(
            base_url=BASE_URL,
            timeout=20,
            cookies={
                "lab_refresh": previous_refresh,
                "lab_csrf": refresh_victim.cookies.get("lab_csrf", ""),
            },
        )
        try:
            replay = await replay_client.post(
                "/api/v2/auth/refresh",
                headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
            )
        finally:
            await replay_client.aclose()
        assert replay.status_code == 401
        assert replay.json()["code"] == "REFRESH_REUSED"
        assert (await refresh_victim.get("/api/v2/auth/me")).status_code == 401
    finally:
        for client, csrf in opened:
            try:
                logout = await client.post(
                    "/api/v2/auth/logout",
                    headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
                )
                # The refresh-replay case intentionally revoked its whole session.
                assert logout.status_code in (200, 401)
            finally:
                await client.aclose()
