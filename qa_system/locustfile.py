"""Locust read-only mixed business and AI API profile for isolated QA."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from threading import Lock

from locust import HttpUser, between, task

QA = Path(__file__).resolve().parent
ACCOUNTS = json.loads((QA / "results" / "accounts.local.json").read_text(encoding="utf-8"))
ACCOUNT_NAMES = ("student_a", "student_b")
_account_counter = itertools.count()
_counter_lock = Lock()


class LabReservationUser(HttpUser):
    wait_time = between(0.2, 0.8)

    def on_start(self) -> None:
        with _counter_lock:
            ordinal = next(_account_counter)
        credentials = ACCOUNTS[ACCOUNT_NAMES[ordinal % len(ACCOUNT_NAMES)]]
        csrf_response = self.client.get("/api/v2/auth/csrf", name="auth/csrf")
        if csrf_response.status_code != 200:
            self.authenticated = False
            return
        csrf = csrf_response.json()["data"]["csrf_token"]
        login = self.client.post(
            "/api/v2/auth/login",
            json=credentials,
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
            name="auth/login",
        )
        self.authenticated = login.status_code == 200

    @task(6)
    def list_devices(self) -> None:
        self.client.get("/api/v2/devices?page=1&page_size=24", name="business/devices")

    @task(3)
    def list_reservations(self) -> None:
        self.client.get(
            "/api/v2/reservations/mine?page=1&page_size=20", name="business/reservations"
        )

    @task(2)
    def list_notifications(self) -> None:
        self.client.get("/api/v2/notifications/mine?page=1&size=20", name="business/notifications")

    @task(2)
    def read_ai_status(self) -> None:
        self.client.get("/api/v2/ai/status", name="ai/status")

    @task(1)
    def list_ai_conversations(self) -> None:
        self.client.get("/api/v2/ai/conversations?limit=50", name="ai/conversations")
