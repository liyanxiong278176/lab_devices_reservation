from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "qa_system"
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def runtime_state() -> dict[str, object]:
    path = QA / ".runtime-secrets.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@pytest.fixture
def qa_state() -> dict[str, object]:
    state = runtime_state()
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
