"""Connectivity probe that never prints credentials or a DSN."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import asyncmy

ROOT = Path(__file__).resolve().parents[1]
STATE = json.loads((ROOT / "qa_system" / ".runtime-secrets.json").read_text(encoding="utf-8"))


async def probe() -> None:
    from sqlalchemy.engine import make_url

    url = make_url(STATE["mysql_dsn"])
    try:
        connection = await asyncmy.connect(
            host=url.host,
            port=url.port or 3306,
            user=url.username,
            password=url.password,
            db=url.database,
            charset="utf8mb4",
            connect_timeout=5,
        )
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                assert await cursor.fetchone() == (1,)
        finally:
            connection.close()
    except Exception as exc:
        raise SystemExit(f"QA MySQL account probe failed: {type(exc).__name__}")
    print("QA MySQL account can connect and query its own schema.")


if __name__ == "__main__":
    asyncio.run(probe())
