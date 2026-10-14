"""Read-only assertions over rows created by the isolated browser suite."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.settings import get_settings  # noqa: E402
from app.infrastructure.db.models import Reservation, ReservationItem  # noqa: E402
from app.infrastructure.db.session import build_engine, build_session_factory  # noqa: E402
from sqlalchemy import func, select  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--purpose", required=True)
    args = parser.parse_args()

    engine = build_engine(get_settings())
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Reservation)
                        .where(Reservation.purpose == args.purpose)
                        .order_by(Reservation.id)
                    )
                ).all()
            )
            details = []
            for row in rows:
                day_count = await session.scalar(
                    select(func.count(ReservationItem.id)).where(
                        ReservationItem.reservation_id == row.id
                    )
                )
                details.append(
                    {
                        "id": row.id,
                        "device_id": row.device_id,
                        "status": row.status,
                        "start_date": row.start_date.isoformat(),
                        "end_date": row.end_date.isoformat(),
                        "reservation_days": int(day_count or 0),
                        "handover_status": row.handover_status,
                    }
                )
            print(json.dumps({"count": len(rows), "reservations": details}, ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
