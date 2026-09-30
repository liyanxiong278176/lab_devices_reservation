"""Measure the real MySQL delayed-association path at its 100k-row boundary."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import secrets
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import Device, User
from app.infrastructure.db.session import build_engine, build_session_factory
from scripts.e2e_fixture import cleanup, seed

ROWS = 100_010
MARKER = f"mysql-deep-page-{secrets.token_hex(8)}"


async def run() -> None:
    settings = Settings()
    database = make_url(settings.mysql_dsn)
    if (
        database.drivername != "mysql+asyncmy"
        or database.host not in {"127.0.0.1", "localhost"}
        or database.port != 33316
        or database.database != "lab_reservation_acceptance"
    ):
        raise SystemExit(
            "Refusing to seed data: set LAB_MYSQL_DSN to the isolated acceptance schema "
            "on 127.0.0.1:33316/lab_reservation_acceptance"
        )

    prefix = f"e2e-deep-page-{secrets.token_hex(6)}"
    seed_output = io.StringIO()
    engine = None
    try:
        with contextlib.redirect_stdout(seed_output):
            await seed(prefix)
        fixture = json.loads(seed_output.getvalue().splitlines()[-1])
        engine = build_engine(settings)
        factory = build_session_factory(engine)

        async with factory() as session:
            user = await session.scalar(select(User).where(User.username == fixture["username"]))
            device = await session.scalar(
                select(Device).where(Device.name == fixture["device_name"])
            )
            if user is None or device is None or user.college_id is None:
                raise AssertionError("isolated deep-page fixture is incomplete")
            user_id = user.id
            college_id = user.college_id
            device_id = device.id
            principal = Principal(
                user_id=user.id,
                username=user.username,
                college_id=user.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id=f"deep-page-{secrets.token_hex(6)}",
                permissions=("reservation:read:own",),
            )

        digit_select = " UNION ALL ".join(
            f"SELECT {value} AS digit" if value == 0 else f"SELECT {value}"
            for value in range(10)
        )
        async with engine.begin() as connection:
            result = await connection.execute(
                text(
                    "INSERT INTO reservation "
                    "(college_id, user_id, device_id, purpose, purpose_category, "
                    "start_date, end_date, status, handover_status) "
                    "SELECT :college_id, :user_id, :device_id, :purpose, 'OTHER', "
                    ":start_date, :end_date, 'COMPLETED', 'RETURNED' "
                    "FROM ("
                    "SELECT d0.digit + 10*d1.digit + 100*d2.digit + "
                    "1000*d3.digit + 10000*d4.digit AS row_num "
                    f"FROM ({digit_select}) d0 "
                    f"CROSS JOIN ({digit_select}) d1 "
                    f"CROSS JOIN ({digit_select}) d2 "
                    f"CROSS JOIN ({digit_select}) d3 "
                    f"CROSS JOIN ({digit_select}) d4 "
                    f"UNION ALL SELECT 100000 + digit AS row_num FROM ({digit_select}) d"
                    ") AS generated_rows "
                    "WHERE row_num < :row_count"
                ),
                {
                    "college_id": college_id,
                    "user_id": user_id,
                    "device_id": device_id,
                    "purpose": MARKER,
                    "start_date": date.today() - timedelta(days=10),
                    "end_date": date.today() - timedelta(days=10),
                    "row_count": ROWS,
                },
            )
            if result.rowcount != ROWS:
                raise AssertionError(f"expected {ROWS} MySQL rows, inserted {result.rowcount}")

        timings_ms: list[float] = []
        last_page = None
        for _ in range(3):
            async with factory() as session:
                started = time.perf_counter()
                last_page = await ReservationService(session, principal).list_mine(
                    page=10_001,
                    page_size=10,
                )
                timings_ms.append((time.perf_counter() - started) * 1000)
        if last_page is None or last_page.total != ROWS or len(last_page.items) != 10:
            raise AssertionError("100k-offset page did not return the expected rows")

        async with factory() as session:
            try:
                await ReservationService(session, principal).list_mine(
                    page=10_002,
                    page_size=10,
                )
            except ApiError as exc:
                over_limit_status = exc.status_code
            else:
                raise AssertionError("page beyond the 100k skip cap was not rejected")

        result = {
            "database": "isolated MySQL 8",
            "synthetic_reservation_rows": ROWS,
            "page": 10_001,
            "page_size": 10,
            "offset": 100_000,
            "returned_rows": len(last_page.items),
            "total_rows": last_page.total,
            "deep_page_latency_ms": {
                "runs": [round(value, 2) for value in timings_ms],
                "median": round(statistics.median(timings_ms), 2),
            },
            "page_10_002_status_at_offset_100_010": over_limit_status,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if over_limit_status != 422:
            raise AssertionError("deep-page boundary returned an unexpected error status")
    finally:
        if engine is not None:
            try:
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM reservation WHERE purpose = :marker"),
                        {"marker": MARKER},
                    )
            finally:
                await engine.dispose()
        await cleanup(prefix)


if __name__ == "__main__":
    asyncio.run(run())
