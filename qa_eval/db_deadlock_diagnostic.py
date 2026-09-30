"""Capture MySQL's most recently detected deadlock without dumping credentials."""

from __future__ import annotations

import asyncio

from config import RESULTS, require_mysql_dsn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(require_mysql_dsn(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            row = (await connection.execute(text("SHOW ENGINE INNODB STATUS"))).first()
            if row is None:
                raise RuntimeError("MySQL did not return InnoDB status")
            status = str(row[2])
        marker = "LATEST DETECTED DEADLOCK"
        start = status.find(marker)
        if start < 0:
            report = "No InnoDB deadlock is currently retained by MySQL.\n"
        else:
            end = status.find("------------", start + len(marker))
            report = status[start : end if end > start else start + 10000]
        destination = RESULTS / "latest-deadlock.txt"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(report, encoding="utf-8")
        print(report[:10000])
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
