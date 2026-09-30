"""Compare the configured application MySQL target with the named container."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncmy
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "qa_system"))
from mysql_admin import execute  # noqa: E402


async def main() -> None:
    old = Path.cwd()
    os.chdir(ROOT / "backend")
    try:
        from app.core.settings import Settings

        url = make_url(Settings().mysql_dsn)
    finally:
        os.chdir(old)
    app = await asyncmy.connect(
        host=url.host,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        db=url.database,
        connect_timeout=5,
    )
    try:
        async with app.cursor() as cursor:
            await cursor.execute("SELECT @@hostname,@@port,@@server_uuid,DATABASE()")
            app_identity = await cursor.fetchone()
    finally:
        app.close()
    container_identity = execute("SELECT @@hostname,@@port,@@server_uuid,DATABASE();")
    print(f"application target: {app_identity}")
    print(f"named mysql container: {container_identity}")


if __name__ == "__main__":
    asyncio.run(main())
