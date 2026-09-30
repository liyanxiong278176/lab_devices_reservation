from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa_system"
BACKEND = ROOT / "backend"
for path in (QA, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _runtime_state() -> dict[str, object]:
    path = QA / ".runtime-secrets.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@pytest.fixture
def qa_state() -> dict[str, object]:
    state = _runtime_state()
    if not state:
        pytest.fail("isolated QA runtime missing; run qa_system/prepare_runtime.py first")
    return state


@pytest.fixture
def api_base_url() -> str:
    return "http://127.0.0.1:8000/api/v2"


@pytest.fixture
def client_factory(api_base_url: str, qa_state: dict[str, object]):
    async def create(account: str = "student_a") -> httpx.AsyncClient:
        credentials_path = QA / "results" / "accounts.local.json"
        accounts = json.loads(credentials_path.read_text(encoding="utf-8"))
        if account not in accounts:
            pytest.fail(f"required QA account is absent: {account}")
        client = httpx.AsyncClient(base_url=api_base_url, timeout=20.0)
        csrf_response = await client.get("/auth/csrf")
        assert csrf_response.status_code == 200
        csrf = csrf_response.json()["data"]["csrf_token"]
        login_response = await client.post(
            "/auth/login",
            json=accounts[account],
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
        )
        assert login_response.status_code == 200, login_response.text
        session_csrf_response = await client.get("/auth/csrf")
        assert session_csrf_response.status_code == 200
        client.headers.update(
            {
                "Origin": "http://127.0.0.1:5173",
                "X-CSRF-Token": session_csrf_response.json()["data"]["csrf_token"],
            }
        )
        return client

    return create


@pytest.fixture
def sync_client(api_base_url: str):
    with httpx.Client(base_url=api_base_url, timeout=20.0) as client:
        yield client


@pytest.fixture(scope="session", autouse=True)
def reset_only_qa_login_buckets():
    """Give this suite a fresh budget in the initially empty, isolated Redis DB."""
    private = QA / ".runtime-secrets.json"
    accounts_path = QA / "results" / "accounts.local.json"
    if not private.exists() or not accounts_path.exists():
        return
    from redis import Redis

    state = json.loads(private.read_text(encoding="utf-8"))
    accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
    keys = ["lab:v2:rate:policy-v2:login_ip:ip:127.0.0.1:login"]
    for account in accounts.values():
        username_hash = hashlib.sha256(account["username"].strip().lower().encode()).hexdigest()[
            :24
        ]
        keys.append(f"lab:v2:rate:policy-v2:login:username:{username_hash}:login")
    client = Redis.from_url(str(state["redis_url"]), socket_timeout=2)
    try:
        client.delete(*keys)
    finally:
        client.close()
