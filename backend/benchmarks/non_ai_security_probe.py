"""Fresh black-box OWASP-style authorization, CSRF, and injection probes.

Run only against an isolated local/test deployment and disposable e2e fixtures.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import Settings
from app.infrastructure.db.models import User
from app.infrastructure.db.session import build_engine, build_session_factory
from scripts.e2e_fixture import validate_prefix
from sqlalchemy import select

API = os.getenv("SECURITY_API", "http://127.0.0.1:18000/api/v2")
ORIGIN = os.getenv("SECURITY_ORIGIN", "http://host.docker.internal:18000")
PASSWORD = "E2e-123456"
PREFIX_A = os.getenv("SECURITY_PREFIX_A", "e2e-sec-a260928")
PREFIX_B = os.getenv("SECURITY_PREFIX_B", "e2e-sec-b260928")


def require(condition: bool, label: str, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"FAIL {label}: {detail}")
    print(f"PASS {label}" + (f" ({detail})" if detail else ""))


def login(username: str) -> tuple[httpx.Client, str]:
    client = httpx.Client(base_url=API, timeout=15)
    csrf = client.get("/auth/csrf")
    require(csrf.status_code == 200, f"CSRF bootstrap {username}")
    token = csrf.json()["data"]["csrf_token"]
    response = client.post(
        "/auth/login",
        json={"username": username, "password": PASSWORD},
        headers={"Origin": ORIGIN, "X-CSRF-Token": token},
    )
    require(response.status_code == 200, f"login {username}")
    access_cookie = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith("lab_access=")
    )
    access_cookie_lower = access_cookie.lower()
    require(
        "httponly" in access_cookie_lower
        and "samesite=lax" in access_cookie_lower
        and "path=/api/v2" in access_cookie_lower,
        f"access cookie attributes {username}",
    )
    return client, response.json()["data"]["csrf_token"]


async def set_user_status(username: str, status: int) -> None:
    engine = build_engine(Settings())
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            user = await session.scalar(select(User).where(User.username == username))
            if user is None:
                raise RuntimeError("isolated security fixture user was not found")
            user.status = status
            await session.commit()
    finally:
        await engine.dispose()


def main() -> None:
    validate_prefix(PREFIX_A)
    validate_prefix(PREFIX_B)
    if PREFIX_A == PREFIX_B:
        raise ValueError("security probe requires two isolated tenant prefixes")

    login_guard = httpx.Client(base_url=API, timeout=15)
    try:
        login_guard.get("/auth/csrf")
        unprotected_login = login_guard.post(
            "/auth/login",
            json={"username": f"{PREFIX_A}-user", "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        require(
            unprotected_login.status_code == 403,
            "login without double-submit CSRF token is denied",
            str(unprotected_login.status_code),
        )
    finally:
        login_guard.close()

    user_a, csrf_a = login(f"{PREFIX_A}-user")
    user_b, csrf_b = login(f"{PREFIX_B}-user")
    manager_a, csrf_manager_a = login(f"{PREFIX_A}-manager")
    try:
        own_a = user_a.get("/devices", params={"search": f"{PREFIX_A}-device"})
        own_b = user_b.get("/devices", params={"search": f"{PREFIX_B}-device"})
        require(own_a.status_code == own_b.status_code == 200, "tenant catalog reads")
        rows_a = own_a.json()["data"]["items"]
        rows_b = own_b.json()["data"]["items"]
        print(f"tenant A search returned {[row['name'] for row in rows_a]}")
        print(f"tenant B search returned {[row['name'] for row in rows_b]}")
        device_a = next((row for row in rows_a if row["name"] == f"{PREFIX_A}-device"), None)
        device_b = next((row for row in rows_b if row["name"] == f"{PREFIX_B}-device"), None)
        require(device_a is not None, "tenant A sees its device")
        require(device_b is not None, "tenant B sees its device")

        hidden_search = user_a.get("/devices", params={"search": f"{PREFIX_B}-device"})
        require(
            hidden_search.status_code == 200
            and all(
                row["name"] != device_b["name"] for row in hidden_search.json()["data"]["items"]
            ),
            "cross-tenant catalog search does not disclose data",
        )
        cross_device = user_a.get(f"/devices/{device_b['id']}")
        require(
            cross_device.status_code in {403, 404},
            "cross-tenant device IDOR denied",
            str(cross_device.status_code),
        )

        malicious_search = user_a.get("/devices", params={"search": "' OR 1=1--"})
        require(
            malicious_search.status_code == 200
            and all(
                row["name"] != device_b["name"] for row in malicious_search.json()["data"]["items"]
            ),
            "SQL-like search input stays tenant-scoped",
        )
        invalid_page = user_a.get("/devices", params={"page": 0})
        require(
            invalid_page.status_code == 422,
            "invalid pagination input is rejected",
            str(invalid_page.status_code),
        )
        hostile_cors = user_a.get("/devices", headers={"Origin": "https://attacker.invalid"})
        require(
            hostile_cors.status_code == 200
            and "access-control-allow-origin" not in hostile_cors.headers,
            "untrusted browser Origin receives no CORS permission",
        )

        availability = user_b.get(
            f"/devices/{device_b['id']}/availability",
            params={
                "start_date": (date.today() + timedelta(days=1)).isoformat(),
                "end_date": (date.today() + timedelta(days=30)).isoformat(),
            },
        )
        require(availability.status_code == 200, "tenant B availability lookup")
        future_day = next(day["date"] for day in availability.json()["data"] if day["available"])
        booking = user_b.post(
            "/reservations",
            json={
                "device_id": device_b["id"],
                "purpose": "isolated tenant authorization probe",
                "purpose_category": "OTHER",
                "start_date": future_day,
                "end_date": future_day,
            },
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_b},
        )
        require(
            booking.status_code == 201,
            "tenant B creates isolated reservation",
            str(booking.status_code),
        )
        reservation_id = booking.json()["data"]["created"][0]["id"]

        cross_reservation = user_a.get(f"/reservations/{reservation_id}")
        require(
            cross_reservation.status_code in {403, 404},
            "cross-tenant reservation IDOR denied",
            str(cross_reservation.status_code),
        )
        cross_approval = manager_a.post(
            f"/approvals/{reservation_id}/approve",
            json={"reason": "must remain tenant scoped"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_manager_a},
        )
        require(
            cross_approval.status_code in {403, 404},
            "cross-tenant manager approval denied",
            str(cross_approval.status_code),
        )

        no_csrf = user_a.post(
            "/reservations",
            json={
                "device_id": device_a["id"],
                "purpose": "missing csrf probe",
                "start_date": future_day,
                "end_date": future_day,
            },
            headers={"Origin": ORIGIN},
        )
        require(
            no_csrf.status_code == 403,
            "state-changing request without CSRF is denied",
            str(no_csrf.status_code),
        )
        untrusted_origin = user_a.post(
            "/reservations",
            json={
                "device_id": device_a["id"],
                "purpose": "untrusted origin probe",
                "start_date": future_day,
                "end_date": future_day,
            },
            headers={"Origin": "https://attacker.invalid", "X-CSRF-Token": csrf_a},
        )
        require(
            untrusted_origin.status_code == 403,
            "untrusted Origin is denied",
            str(untrusted_origin.status_code),
        )

        anonymous = httpx.get(f"{API}/reservations/mine", timeout=15)
        require(
            anonymous.status_code == 401,
            "anonymous reservation request is denied",
            str(anonymous.status_code),
        )

        disabled_username = f"{PREFIX_A}-user"
        asyncio.run(set_user_status(disabled_username, 0))
        try:
            revoked = user_a.get("/auth/me")
            require(
                revoked.status_code == 401,
                "disabled account invalidates existing session",
                str(revoked.status_code),
            )
        finally:
            asyncio.run(set_user_status(disabled_username, 1))

        old_refresh = manager_a.cookies.get("lab_refresh")
        require(old_refresh is not None, "refresh cookie exists before rotation")
        rotated = manager_a.post(
            "/auth/refresh",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_manager_a},
        )
        require(rotated.status_code == 200, "refresh token rotates", str(rotated.status_code))
        manager_a.cookies.set(
            "lab_refresh",
            old_refresh,
            domain="127.0.0.1",
            path="/api/v2/auth",
        )
        replay = manager_a.post(
            "/auth/refresh",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_manager_a},
        )
        require(
            replay.status_code == 401 and replay.json().get("code") == "REFRESH_REUSED",
            "replayed refresh token is rejected and revokes the session",
            str(replay.status_code),
        )
        revoked_session = manager_a.get("/auth/me")
        require(
            revoked_session.status_code == 401,
            "refresh replay revokes access session",
            str(revoked_session.status_code),
        )
    finally:
        user_a.close()
        user_b.close()
        manager_a.close()


if __name__ == "__main__":
    main()
