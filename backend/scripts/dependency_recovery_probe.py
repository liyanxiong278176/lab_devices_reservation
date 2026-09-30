"""Verify live API behavior during isolated MySQL and Redis outages.

This probe can stop only the two uniquely named throw-away acceptance
containers created for this test suite. It never targets the developer's
``lab-mysql`` or ``lab-redis`` containers.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.e2e_fixture import cleanup, seed

MYSQL_CONTAINER = "codex-lab-acceptance-mysql"
REDIS_CONTAINER = "codex-lab-acceptance-redis"


def docker(*arguments: str) -> str:
    completed = subprocess.run(
        ["docker", *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.stdout.strip()


async def wait_for_dependency(container: str, *, mysql: bool) -> bool:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if mysql:
                health = docker("inspect", "--format", "{{.State.Health.Status}}", container)
                if health == "healthy":
                    return True
            elif docker("exec", container, "redis-cli", "ping") == "PONG":
                return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        await asyncio.sleep(1)
    return False


async def login(
    client: httpx.AsyncClient,
    *,
    username: str,
    password: str,
    origin: str,
) -> None:
    csrf_response = await client.get("/api/v2/auth/csrf")
    if csrf_response.status_code != 200:
        raise AssertionError(f"CSRF bootstrap returned HTTP {csrf_response.status_code}")
    token = csrf_response.json()["data"]["csrf_token"]
    response = await client.post(
        "/api/v2/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": origin, "X-CSRF-Token": token},
    )
    if response.status_code != 200:
        raise AssertionError(
            f"isolated login returned HTTP {response.status_code}: {response.text[:500]}"
        )


async def status(client: httpx.AsyncClient, path: str) -> int:
    return (await client.get(path)).status_code


async def run(args: argparse.Namespace) -> None:
    prefix = f"e2e-recovery-{secrets.token_hex(6)}"
    seed_output = io.StringIO()
    try:
        with contextlib.redirect_stdout(seed_output):
            await seed(prefix)
        fixture = json.loads(seed_output.getvalue().splitlines()[-1])
        origin = args.origin
        base_url = args.base_url.rstrip("/")

        async with httpx.AsyncClient(base_url=base_url, timeout=10, trust_env=False) as client:
            await login(
                client,
                username=fixture["admin_username"],
                password=fixture["password"],
                origin=origin,
            )
            auth_before = await status(client, "/api/v2/auth/me")
            ready_before = await status(client, "/api/v2/ready")
            if (auth_before, ready_before) != (200, 200):
                raise AssertionError("API was not healthy before fault injection")

            docker("stop", REDIS_CONTAINER)
            redis_down_auth = await status(client, "/api/v2/auth/me")
            live_during_redis = await status(client, "/api/v2/live")
            docker("start", REDIS_CONTAINER)
            if not await wait_for_dependency(REDIS_CONTAINER, mysql=False):
                raise AssertionError("isolated Redis did not restart")
            await asyncio.sleep(6)  # let the Redis circuit breaker enter half-open state
            old_session_after_redis = await status(client, "/api/v2/auth/me")

            fresh = httpx.AsyncClient(base_url=base_url, timeout=10, trust_env=False)
            try:
                await login(
                    fresh,
                    username=fixture["admin_username"],
                    password=fixture["password"],
                    origin=origin,
                )
                auth_after_redis = await status(fresh, "/api/v2/auth/me")
                ready_after_redis = await status(fresh, "/api/v2/ready")
                redis_result = {
                    "redis_down_auth": redis_down_auth,
                    "liveness_during_redis_outage": live_during_redis,
                    "old_session_after_redis_restart": old_session_after_redis,
                    "fresh_login_after_redis_restart": auth_after_redis,
                    "readiness_after_redis_restart": ready_after_redis,
                }
                print(json.dumps(redis_result, ensure_ascii=False, indent=2))
                if (
                    redis_down_auth != 503
                    or live_during_redis != 200
                    # A graceful Redis restart may preserve its RDB; if it
                    # does not, the old session must fail closed as 401.
                    or old_session_after_redis not in {200, 401}
                    or auth_after_redis != 200
                    or ready_after_redis != 200
                ):
                    raise AssertionError("Redis outage did not fail closed or recover cleanly")

                docker("stop", MYSQL_CONTAINER)
                ready_during_mysql = await status(fresh, "/api/v2/ready")
                live_during_mysql = await status(fresh, "/api/v2/live")
                docker("start", MYSQL_CONTAINER)
                if not await wait_for_dependency(MYSQL_CONTAINER, mysql=True):
                    raise AssertionError("isolated MySQL did not restart")
                ready_after_mysql = await status(fresh, "/api/v2/ready")
            finally:
                await fresh.aclose()

        result = {
            "auth_before": auth_before,
            "readiness_before": ready_before,
            "redis_down_auth": redis_down_auth,
            "liveness_during_redis_outage": live_during_redis,
            "old_session_after_redis_restart": old_session_after_redis,
            "fresh_login_after_redis_restart": auth_after_redis,
            "readiness_after_redis_restart": ready_after_redis,
            "readiness_during_mysql_outage": ready_during_mysql,
            "liveness_during_mysql_outage": live_during_mysql,
            "readiness_after_mysql_restart": ready_after_mysql,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if (ready_during_mysql, live_during_mysql, ready_after_mysql) != (503, 200, 200):
            raise AssertionError("MySQL outage did not fail readiness or recover cleanly")
    finally:
        # If a probe assertion fails during an outage, restore dependencies
        # before cleaning up fixture rows or returning control to the caller.
        for container in (REDIS_CONTAINER, MYSQL_CONTAINER):
            with contextlib.suppress(subprocess.CalledProcessError, subprocess.TimeoutExpired):
                docker("start", container)
        with contextlib.suppress(AssertionError):
            await wait_for_dependency(REDIS_CONTAINER, mysql=False)
            await wait_for_dependency(MYSQL_CONTAINER, mysql=True)
        await cleanup(prefix)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--origin", default="http://127.0.0.1:15173")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
