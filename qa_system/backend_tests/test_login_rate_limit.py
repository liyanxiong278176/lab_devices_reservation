from __future__ import annotations

import httpx


async def test_password_guessing_is_limited_after_five_attempts() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000/api/v2", timeout=15) as client:
        csrf = await client.get("/auth/csrf")
        assert csrf.status_code == 200
        token = csrf.json()["data"]["csrf_token"]
        statuses = []
        last = None
        for _ in range(6):
            last = await client.post(
                "/auth/login",
                json={"username": "QAEVAL_bruteforce_probe", "password": "wrong-password"},
                headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": token},
            )
            statuses.append(last.status_code)
        assert statuses[:5] == [401] * 5
        assert statuses[5] == 429
        assert last is not None
        assert last.json()["code"] == "RATE_LIMITED"
        assert int(last.json()["data"]["retry_after"]) >= 1
