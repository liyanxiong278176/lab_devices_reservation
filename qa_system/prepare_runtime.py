"""Create a disposable, uniquely named runtime without touching project .env files."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from mysql_admin import execute as execute_mysql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
QA = ROOT / "qa_system"
PUBLIC_STATE = QA / "results" / "runtime.json"
PRIVATE_STATE = QA / ".runtime-secrets.json"


def load_backend_settings():
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    from app.core.settings import Settings

    return Settings()


def main() -> int:
    if PRIVATE_STATE.exists() or PUBLIC_STATE.exists():
        raise RuntimeError(
            "A QA runtime manifest already exists; inspect and clean that exact run first"
        )
    settings = load_backend_settings()
    source_url = make_url(settings.mysql_dsn)
    redis_url = make_url(settings.redis_url)
    if source_url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Refusing to create a QA schema against a non-local MySQL host")
    if source_url.database != "lab_reservation":
        raise RuntimeError(
            "Refusing isolation setup: source schema is not the expected local lab_reservation"
        )
    if redis_url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Refusing to select a Redis DB on a non-local host")

    from redis import Redis

    chosen_redis_db = None
    for candidate in range(15, 0, -1):
        candidate_url = redis_url.set(database=str(candidate)).render_as_string(hide_password=False)
        client = Redis.from_url(candidate_url, socket_timeout=2)
        try:
            client.ping()
            if client.dbsize() == 0:
                chosen_redis_db = candidate
                break
        finally:
            client.close()
    if chosen_redis_db is None:
        raise RuntimeError("No empty non-default Redis DB is available; no QA runtime was created")

    suffix = secrets.token_hex(4)
    schema = f"lab_reservation_qa_{suffix}"
    username = f"qaeval_{suffix}"
    password = secrets.token_urlsafe(32)
    admin_username = f"qa_admin_{suffix}"
    admin_password = secrets.token_urlsafe(32)
    jwt_secret = secrets.token_urlsafe(48)
    database_host = source_url.host or "127.0.0.1"
    database_port = source_url.port or 3306

    schema_ident = f"`{schema}`"
    user_ident = f"'{username}'@'%'"
    qa_mysql_url = source_url.set(
        database=schema,
        username=username,
        password=password,
        query={key: value for key, value in source_url.query.items()},
    )
    qa_redis_url = redis_url.set(database=str(chosen_redis_db))
    collection = f"qaeval_{suffix}"
    private = {
        "schema": schema,
        "mysql_host": database_host,
        "mysql_port": database_port,
        "mysql_user": username,
        "mysql_password": password,
        "mysql_dsn": qa_mysql_url.render_as_string(hide_password=False),
        "redis_url": qa_redis_url.render_as_string(hide_password=False),
        "redis_database": chosen_redis_db,
        "qdrant_collection": collection,
        "admin_username": admin_username,
        "admin_password": admin_password,
        "jwt_secret": jwt_secret,
        "suffix": suffix,
        "root_password_env_source": "DB_ROOT_PASSWORD",
    }
    PUBLIC_STATE.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE_STATE.write_text(json.dumps(private, indent=2), encoding="utf-8")
    PUBLIC_STATE.write_text(
        json.dumps(
            {
                "run_prefix": f"QAEVAL_{suffix}",
                "schema": schema,
                "redis_database": chosen_redis_db,
                "qdrant_collection": collection,
                "migration_head_before": "0036_knowledge_build_ordering",
                "live_provider": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    app_password_sql = password.replace("'", "''")
    try:
        execute_mysql(
            f"CREATE DATABASE {schema_ident} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;\n"
            f"CREATE USER {user_ident} IDENTIFIED BY '{app_password_sql}';\n"
            f"GRANT ALL PRIVILEGES ON {schema_ident}.* TO {user_ident};\n"
        )
    except Exception:
        # Only these just-generated identifiers are eligible for rollback.
        try:
            execute_mysql(
                f"DROP DATABASE IF EXISTS {schema_ident};\nDROP USER IF EXISTS {user_ident};\n"
            )
        except Exception:
            pass
        PRIVATE_STATE.unlink(missing_ok=True)
        PUBLIC_STATE.unlink(missing_ok=True)
        raise

    env = os.environ.copy()
    env["LAB_MYSQL_DSN"] = private["mysql_dsn"]
    migration = subprocess.run(
        [str(BACKEND / ".venv" / "Scripts" / "python.exe"), "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    (QA / "results" / "migration.log").write_text(
        migration.stdout + migration.stderr,
        encoding="utf-8",
    )
    if migration.returncode:
        raise RuntimeError(
            "Isolated QA schema migration failed; see qa_system/results/migration.log"
        )
    print(json.dumps(json.loads(PUBLIC_STATE.read_text(encoding="utf-8")), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"QA runtime not prepared: {exc}", file=sys.stderr)
        raise SystemExit(2)
