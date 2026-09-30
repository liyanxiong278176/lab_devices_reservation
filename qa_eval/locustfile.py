"""Independent Locust personas for the laboratory reservation workflow."""

from __future__ import annotations

import itertools
import json
import logging
import os
import random
import uuid
from datetime import date, timedelta
from pathlib import Path

import psutil
from locust import HttpUser, LoadTestShape, between, task
from locust.exception import StopUser

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(
    os.getenv("QA_FIXTURE_FILE", str(ROOT / "qa_eval" / "results" / "fixture.json"))
)
if not MANIFEST_PATH.is_absolute():
    MANIFEST_PATH = ROOT / MANIFEST_PATH
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
PASSWORD = MANIFEST["password"]
_student_indexes = {"CSE": itertools.count(), "BIO": itertools.count()}


class AuthenticatedPersona(HttpUser):
    abstract = True
    wait_time = between(1, 5)
    role = "student"
    college = "CSE"

    def account(self) -> dict[str, object]:
        if self.role == "student":
            accounts = MANIFEST["accounts"]["students"][self.college]
            return accounts[next(_student_indexes[self.college]) % len(accounts)]
        if self.role == "manager":
            return MANIFEST["accounts"]["managers"][self.college]
        return MANIFEST["accounts"]["admin"]

    def on_start(self) -> None:
        account = self.account()
        bootstrap = self.client.get("/api/v2/auth/csrf", name="/auth/csrf")
        if bootstrap.status_code != 200:
            raise StopUser("CSRF bootstrap failed")
        csrf = bootstrap.json()["data"]["csrf_token"]
        login = self.client.post(
            "/api/v2/auth/login",
            json={"username": account["username"], "password": PASSWORD},
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
            name="/auth/login",
        )
        if login.status_code != 200:
            raise StopUser("QA account login failed")
        self.csrf = login.json()["data"]["csrf_token"]
        self.headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": self.csrf,
        }

    @task(6)
    def browse_devices(self) -> None:
        with self.client.get(
            "/api/v2/devices",
            params={"page": 1, "page_size": 20},
            name="/devices [list]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"unexpected HTTP {response.status_code}")

    @task(3)
    def own_reservations(self) -> None:
        with self.client.get(
            "/api/v2/reservations/mine",
            params={"page": 1, "page_size": 20},
            name="/reservations/mine",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"unexpected HTTP {response.status_code}")

    @task(2)
    def notification_center(self) -> None:
        with self.client.get(
            "/api/v2/notifications/mine",
            params={"page": 1, "size": 20},
            name="/notifications/mine",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"unexpected HTTP {response.status_code}")

    @task(2)
    def dashboard(self) -> None:
        with self.client.get(
            "/api/v2/dashboard/summary",
            name="/dashboard/summary",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"unexpected HTTP {response.status_code}")

    @task(1)
    def reserve_one_day(self) -> None:
        # Keep writes inside the current tenant; cross-tenant traffic belongs
        # in the dedicated security probes and is an expected denial there.
        device_group = self.college if self.role != "admin" else random.choice(["CSE", "BIO"])
        device_id = random.choice(MANIFEST["device_ids"][device_group][1::2])
        day = date.today() + timedelta(days=random.randint(1, 28))
        headers = dict(self.headers)
        headers["Idempotency-Key"] = f"locust-{MANIFEST['run_id']}-{uuid.uuid4().hex}"
        with self.client.post(
            "/api/v2/reservations",
            json={
                "device_id": device_id,
                "start_date": day.isoformat(),
                "end_date": day.isoformat(),
                "purpose": "qa_eval performance reservation",
            },
            headers=headers,
            name="/reservations [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (201, 409):
                response.success()
            else:
                response.failure(f"unexpected HTTP {response.status_code}")


class StudentUser(AuthenticatedPersona):
    weight = 10
    role = "student"
    college = "CSE"


class BioStudentUser(AuthenticatedPersona):
    weight = 4
    role = "student"
    college = "BIO"


class ManagerUser(AuthenticatedPersona):
    weight = 2
    role = "manager"
    college = "CSE"

    @task(2)
    def pending_approvals(self) -> None:
        with self.client.get(
            "/api/v2/approvals/pending",
            params={"page": 1, "page_size": 20},
            name="/approvals/pending",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"unexpected HTTP {response.status_code}")

    @task(1)
    def pending_handovers(self) -> None:
        with self.client.get(
            "/api/v2/reservations/handovers",
            params={"status": "PENDING", "page": 1, "page_size": 20},
            name="/reservations/handovers",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"unexpected HTTP {response.status_code}")


class SystemAdminUser(AuthenticatedPersona):
    weight = 1
    role = "admin"

    @task(2)
    def list_users(self) -> None:
        with self.client.get(
            "/api/v2/users",
            params={"page": 1, "size": 20},
            name="/users [admin list]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"unexpected HTTP {response.status_code}")


class UnauthenticatedProbe(HttpUser):
    """Low-weight negative security traffic; expected 401s are not load failures."""

    weight = 1
    wait_time = between(3, 5)

    @task
    def protected_resource_without_cookie(self) -> None:
        with self.client.get(
            "/api/v2/devices",
            name="/devices [anonymous expected 401]",
            catch_response=True,
        ) as response:
            if response.status_code in (401, 403):
                response.success()
            else:
                response.failure(f"expected auth rejection, got HTTP {response.status_code}")


class AttackerUser(AuthenticatedPersona):
    """Low-weight authenticated probes for tenant isolation and CSRF controls."""

    weight = 1
    role = "student"
    college = "CSE"

    @task(3)
    def cross_tenant_device_read(self) -> None:
        foreign_id = MANIFEST["device_ids"]["BIO"][0]
        with self.client.get(
            f"/api/v2/devices/{foreign_id}",
            name="/devices/[id] [cross-tenant expected deny]",
            catch_response=True,
        ) as response:
            if response.status_code in (403, 404):
                response.success()
            else:
                response.failure(f"expected tenant denial, got HTTP {response.status_code}")

    @task(2)
    def missing_csrf_write(self) -> None:
        day = date.today() + timedelta(days=29)
        with self.client.post(
            "/api/v2/reservations",
            json={
                "device_id": MANIFEST["device_ids"]["CSE"][0],
                "start_date": day.isoformat(),
                "end_date": day.isoformat(),
                "purpose": "qa_eval expected CSRF denial",
            },
            headers={"Origin": "http://127.0.0.1:5173"},
            name="/reservations [missing CSRF expected deny]",
            catch_response=True,
        ) as response:
            if response.status_code in (400, 403):
                response.success()
            else:
                response.failure(f"expected CSRF denial, got HTTP {response.status_code}")

    @task(1)
    def forged_origin_write(self) -> None:
        day = date.today() + timedelta(days=29)
        headers = dict(self.headers)
        headers["Origin"] = "https://attacker.example"
        with self.client.post(
            "/api/v2/reservations",
            json={
                "device_id": MANIFEST["device_ids"]["CSE"][0],
                "start_date": day.isoformat(),
                "end_date": day.isoformat(),
                "purpose": "qa_eval expected origin denial",
            },
            headers=headers,
            name="/reservations [forged Origin expected deny]",
            catch_response=True,
        ) as response:
            if response.status_code in (400, 403):
                response.success()
            else:
                response.failure(f"expected Origin denial, got HTTP {response.status_code}")


class EvaluationShape(LoadTestShape):
    """Optional staircase, stress, and spike profiles selected by QA_PROFILE."""

    def tick(self):
        profile = os.getenv("QA_PROFILE", "")
        elapsed = self.get_run_time()
        runner = self.runner
        total = runner.stats.total if runner is not None else None
        min_requests = int(os.getenv("QA_BREAK_MIN_REQUESTS", "50"))
        max_fail_ratio = float(os.getenv("QA_BREAK_FAIL_RATIO", "0.03"))
        max_p95_ms = float(os.getenv("QA_BREAK_P95_MS", "1500"))
        max_memory_percent = float(os.getenv("QA_BREAK_MEMORY_PERCENT", "90"))
        memory_percent = psutil.virtual_memory().percent
        if memory_percent >= max_memory_percent:
            logging.getLogger("locust.shape").warning(
                "Stopping %s profile at %.1fs: host_memory_percent=%.1f limit=%.1f",
                profile,
                elapsed,
                memory_percent,
                max_memory_percent,
            )
            return None
        if total is not None and total.num_requests >= min_requests:
            if (
                total.fail_ratio >= max_fail_ratio
                or total.get_response_time_percentile(0.95) >= max_p95_ms
            ):
                logging.getLogger("locust.shape").warning(
                    "Stopping %s profile at %.1fs: requests=%d fail_ratio=%.4f p95_ms=%.1f",
                    profile,
                    elapsed,
                    total.num_requests,
                    total.fail_ratio,
                    total.get_response_time_percentile(0.95),
                )
                return None
        if profile in ("load", "soak"):
            duration = int(os.getenv("QA_DURATION_SECONDS", "60"))
            if elapsed >= duration:
                return None
            users = int(os.getenv("QA_USERS", "25"))
            return users, max(1, int(os.getenv("QA_SPAWN_RATE", "5")))
        if profile == "stairs":
            stage_seconds = int(os.getenv("QA_STAGE_SECONDS", "60"))
            stages = [10, 25, 50, 100, 200]
            index = int(elapsed // stage_seconds)
            if index >= len(stages):
                return None
            return stages[index], max(2, stages[index] // 10)
        if profile == "stress":
            stage_seconds = int(os.getenv("QA_STAGE_SECONDS", "45"))
            stages = [25, 50, 100, 150, 200, 250]
            index = int(elapsed // stage_seconds)
            if index >= len(stages):
                return None
            return stages[index], 10
        if profile == "spike":
            stages = [(0, 10, 5), (30, 100, 25), (75, 100, 10), (105, 10, 10), (135, 10, 5)]
            current = None
            for start, users, spawn in stages:
                if elapsed >= start:
                    current = (users, spawn)
            if elapsed >= 165:
                return None
            return current
        return None
