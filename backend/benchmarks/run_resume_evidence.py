"""Run real MySQL/Redis/browser proof and HTTP pagination A/B in an isolated schema.

From backend: uv run python benchmarks/run_resume_evidence.py
Creates one uniquely named MySQL schema and one disposable Redis container.
Uses ports 8005/8006/8007/5175/6392, refuses existing listeners, and always stops
only its own processes/container and drops only the schema it just created.
Does not edit .env, existing migrations, or production pagination.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import psutil
from app.core.settings import Settings
from app.infrastructure.db.models import Reservation, User
from app.infrastructure.db.pagination import delayed_page_ids
from app.infrastructure.db.session import build_engine, build_session_factory
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
FRONTEND = ROOT / "frontend"


def root_sql(sql: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "lab-mysql",
            "sh",
            "-c",
            'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --batch --skip-column-names',
        ],
        input=sql,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # Do not print connection strings or credential-bearing commands.
        raise RuntimeError(f"Isolated schema administration failed: {result.stderr[-600:]}")
    return result.stdout.strip()


def wait_http(url: str, process: subprocess.Popen, seconds: int = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned test server stopped; inspect its local log")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Owned test server did not become ready: {url}")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    parent = psutil.Process(process.pid)
    children = parent.children(recursive=True)
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    for child in children:
        try:
            if child.is_running():
                child.kill()
        except psutil.NoSuchProcess:
            pass


async def database_evidence(output: Path, username: str, rows_count: int = 10_000) -> None:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            table_name = Reservation.__tablename__
            indexes_before = (
                (await session.execute(text(f"SHOW INDEX FROM `{table_name}`"))).mappings().all()
            )
            analyze = (
                (await session.execute(text(f"ANALYZE TABLE `{table_name}`"))).mappings().all()
            )
            await session.commit()
            user = await session.scalar(select(User).where(User.username == username))
            if user is None:
                raise RuntimeError("Missing isolated performance user")
            conditions = [Reservation.user_id == user.id, Reservation.college_id == user.college_id]
            deepest_page = rows_count // 20
            offset = (deepest_page - 1) * 20
            id_page = delayed_page_ids(
                select(Reservation.id).where(*conditions),
                Reservation.id,
                page=deepest_page,
                page_size=20,
            )
            statements = {
                "traditional": select(Reservation)
                .where(*conditions)
                .order_by(Reservation.id.desc())
                .offset(offset)
                .limit(20),
                "deferred": select(Reservation)
                .join(id_page, id_page.c.id == Reservation.id)
                .order_by(Reservation.id.desc()),
            }
            plans = {}
            for name, statement in statements.items():
                sql = str(
                    statement.compile(
                        dialect=engine.dialect, compile_kwargs={"literal_binds": True}
                    )
                )
                rows = (await session.execute(text("EXPLAIN ANALYZE " + sql))).all()
                plans[name] = {"sql": sql, "explain_analyze": [row[0] for row in rows]}
            indexes = (
                (await session.execute(text(f"SHOW INDEX FROM `{Reservation.__tablename__}`")))
                .mappings()
                .all()
            )
            version = await session.scalar(text("SELECT VERSION()"))
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            evidence = {
                "mysql_version": version,
                "alembic_head": revision,
                "indexes_before_analyze": [dict(row) for row in indexes_before],
                "analyze_table": [dict(row) for row in analyze],
                "indexes": [dict(row) for row in indexes],
                "rows": rows_count,
                "deepest_page": deepest_page,
                f"page_{deepest_page}_plans": plans,
            }
            (output / "database-evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
    finally:
        await engine.dispose()


def main() -> None:
    # Windows redirected consoles otherwise use GBK for Playwright's Unicode output.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--rounds", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--pagination-study", action="store_true")
    parser.add_argument("--http-requests", type=int, default=250)
    parser.add_argument("--sql-requests", type=int, default=500)
    parser.add_argument("--rows", type=int, choices=(10_000, 100_000), default=10_000)
    args = parser.parse_args()
    if args.rounds is None:
        args.rounds = 4 if args.pagination_study else 6
    if args.concurrency < 1 or args.rounds < 1:
        parser.error("concurrency and rounds must be positive")
    if args.pagination_study and args.concurrency != 1:
        parser.error("the pagination study requires concurrency=1")
    if args.rows != 10_000 and not args.pagination_study:
        parser.error("custom row counts require --pagination-study")
    if args.http_requests < 1 or args.sql_requests < 1:
        parser.error("request counts must be positive")
    run_id = datetime.now(ZoneInfo("Asia/Singapore")).strftime("%Y%m%d-%H%M%S")
    token = secrets.token_hex(4)
    output = (args.output or ROOT / ".artifacts" / f"resume-evidence-{run_id}-{token}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    schema = f"lab_resume_{token}"
    container = f"lab-resume-redis-{token}"
    settings = Settings()
    url = make_url(settings.mysql_dsn)
    if url.host not in {"127.0.0.1", "localhost"} or url.port not in {None, 3306}:
        raise RuntimeError("This harness accepts only the local Compose MySQL")
    if not re.fullmatch(r"[a-zA-Z0-9_]+", url.username or ""):
        raise RuntimeError("Unexpected local MySQL account name")
    for port in (8005, 8006, 8007, 5175, 6392):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is already occupied; no service was stopped")
    env = dict(os.environ)
    env.update(
        {
            "LAB_MYSQL_DSN": url.set(database=schema).render_as_string(hide_password=False),
            "LAB_REDIS_URL": "redis://127.0.0.1:6392/14",
            "LAB_ENVIRONMENT": "local",
            "LAB_RATE_LIMIT_ENABLED": "false",
            "LAB_DEBUG": "false",
            "LAB_DB_POOL_SIZE": "10",
            "LAB_DB_MAX_OVERFLOW": "20",
            "LAB_CORS_ORIGINS": '["http://127.0.0.1:5175"]',
            "LAB_NOTIFICATION_STREAM_GROUP_ID": f"lab:v2:notification:process:e2e-{token}",
            "E2E_BACKEND_PORT": "8005",
            "E2E_BASE_URL": "http://127.0.0.1:5175",
            "E2E_NOTIFICATION_PREFIX": f"e2e-resume-{token}",
            "E2E_NOTIFICATION_EVIDENCE_DIR": str(output / "notification"),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
    if not pnpm:
        raise RuntimeError("pnpm is required")
    processes: list[subprocess.Popen] = []
    handles = []
    schema_created = False
    container_created = False

    def command(arguments: list[str], cwd: Path = BACKEND, log: str | None = None) -> str:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if log:
            (output / log).write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"Measurement command failed; inspect {log or 'local logs'}")
        return result.stdout

    def start(arguments: list[str], log: str, cwd: Path = BACKEND) -> subprocess.Popen:
        handle = (output / log).open("w", encoding="utf-8")
        handles.append(handle)
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        processes.append(process)
        return process

    print(f"Evidence directory: {output}", flush=True)
    try:
        root_sql(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        schema_created = True
        if url.username != "root":
            root_sql(f"GRANT ALL PRIVILEGES ON `{schema}`.* TO '{url.username}'@'%';")
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                "-p",
                "127.0.0.1:6392:6379",
                "redis:7-alpine",
            ]
        )
        container_created = True
        command(["uv", "run", "alembic", "upgrade", "head"], log="migration.log")
        print("Isolated schema migrated; starting notification API", flush=True)
        env["LAB_ENABLE_WORKERS"] = "true"
        api = start(
            [
                "uv",
                "run",
                "uvicorn",
                "app.main:app",
                "--loop",
                "app.core.uvicorn_loop:platform_loop_factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8005",
                "--no-access-log",
            ],
            "notification-api.log",
        )
        wait_http("http://127.0.0.1:8005/api/v2/live", api)
        if not args.skip_browser:
            vite = start(
                [pnpm, "exec", "vite", "--config", "e2e/vite.resume.config.ts"],
                "frontend.log",
                FRONTEND,
            )
            wait_http("http://127.0.0.1:5175", vite)
            browser_result = command(
                [
                    pnpm,
                    "test:e2e",
                    "--config",
                    "e2e/playwright.resume.config.ts",
                    "--grep",
                    "用例2",
                ],
                FRONTEND,
                "browser.log",
            )
            print(browser_result, flush=True)
            stop_process(vite)
        stop_process(api)
        print("Starting same-data pagination comparison", flush=True)
        prefix = f"e2e-perf-{token}"
        fixture = json.loads(
            command(["uv", "run", "python", "scripts/e2e_fixture.py", "seed", "--prefix", prefix])
        )
        command(
            [
                "uv",
                "run",
                "python",
                "benchmarks/http_read_capacity.py",
                "seed-history",
                "--prefix",
                prefix,
                "--rows",
                str(args.rows),
            ],
            log="history-seed.log",
        )
        os.environ.update({key: value for key, value in env.items() if key.startswith("LAB_")})
        asyncio.run(database_evidence(output, fixture["username"], args.rows))
        env["LAB_ENABLE_WORKERS"] = "false"
        for strategy, port in (("traditional", 8006), ("deferred", 8007)):
            process = start(
                [
                    "uv",
                    "run",
                    "python",
                    "benchmarks/pagination_compare.py",
                    "serve",
                    "--strategy",
                    strategy,
                    "--port",
                    str(port),
                ],
                f"{strategy}-api.log",
            )
            wait_http(f"http://127.0.0.1:{port}/api/v2/live", process)
        measurement_args = [
            "uv",
            "run",
            "python",
            "benchmarks/pagination_diagnostics.py"
            if args.pagination_study
            else "benchmarks/pagination_compare.py",
        ]
        if not args.pagination_study:
            measurement_args.append("compare")
        measurement_args.extend(
            [
                "--username",
                fixture["username"],
                "--password",
                fixture["password"],
                "--rounds",
                str(args.rounds),
                "--output",
                str(output),
            ]
        )
        if args.pagination_study:
            measurement_args.extend(
                [
                    "--http-requests",
                    str(args.http_requests),
                    "--sql-requests",
                    str(args.sql_requests),
                    "--rows",
                    str(args.rows),
                ]
            )
        else:
            measurement_args.extend(["--concurrency", str(args.concurrency)])
        result = command(
            measurement_args,
            log="pagination-run.log",
        )
        print(result, flush=True)
        metadata = {
            "measured_at": datetime.now(ZoneInfo("Asia/Singapore")).isoformat(),
            "platform": platform.platform(),
            "logical_cpus": psutil.cpu_count(),
            "physical_cpus": psutil.cpu_count(logical=False),
            "memory_gib": round(psutil.virtual_memory().total / 1024**3, 2),
            "isolated_schema": schema,
            "redis_container": container,
            "browser_executed": not args.skip_browser,
            "pagination_concurrency": args.concurrency,
            "pagination_study": args.pagination_study,
            "reservation_rows": args.rows,
            "source_sha256": {
                str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (
                    BACKEND / "app/application/reservations.py",
                    BACKEND / "benchmarks/pagination_compare.py",
                    BACKEND / "benchmarks/pagination_diagnostics.py",
                    FRONTEND / "e2e/notification-stream-live.spec.ts",
                )
            },
        }
        (output / "environment.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print("Measurements completed", flush=True)
    finally:
        cleanup = {
            "isolated_schema": schema,
            "owned_servers_stopped": False,
            "redis_container_removed": False,
            "schema_removed": False,
        }
        for process in reversed(processes):
            stop_process(process)
        cleanup["owned_servers_stopped"] = True
        for handle in handles:
            handle.close()
        if container_created:
            result = subprocess.run(["docker", "rm", "-f", container], capture_output=True)
            cleanup["redis_container_removed"] = result.returncode == 0
        if schema_created:
            # The only drop target is the exact random schema created above.
            if re.fullmatch(r"lab_resume_[a-f0-9]{8}", schema) is None:
                raise RuntimeError("Refusing unexpected cleanup schema")
            if url.username != "root":
                root_sql(f"REVOKE ALL PRIVILEGES ON `{schema}`.* FROM '{url.username}'@'%';")
            root_sql(f"DROP DATABASE `{schema}`;")
            cleanup["schema_removed"] = True
        (output / "cleanup.json").write_text(json.dumps(cleanup, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
