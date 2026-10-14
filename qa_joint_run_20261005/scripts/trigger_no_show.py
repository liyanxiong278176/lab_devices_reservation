"""Process one isolated QA reservation's real no-show outbox task immediately.

The event timestamp remains the reservation's natural-day end in production
logic; this helper only claims that specific outbox row so the browser run
does not wait until midnight.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from fastapi import FastAPI
from sqlalchemy import select, update

from app.core.settings import get_settings
from app.infrastructure.db.models import OutboxTask, PenaltyCase, Reservation
from app.infrastructure.db.session import build_engine, build_session_factory
from app.infrastructure.tasks.worker import OutboxWorker, utcnow_naive


async def run(reservation_id: int) -> None:
    settings = get_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    app = FastAPI()
    app.state.settings = settings
    app.state.session_factory = factory
    worker = OutboxWorker(app)
    try:
        async with factory() as session:
            task = await session.scalar(
                select(OutboxTask)
                .where(
                    OutboxTask.task_key == f"timeout:reservation:{reservation_id}:no-show",
                    OutboxTask.task_type == "RESERVATION_NO_SHOW",
                )
                .with_for_update()
            )
            if task is None or task.status != "PENDING":
                raise RuntimeError("The reservation has no pending no-show task to process")
            result = await session.execute(
                update(OutboxTask)
                .where(OutboxTask.id == task.id, OutboxTask.status == "PENDING")
                .values(
                    status="PROCESSING",
                    attempts=OutboxTask.attempts + 1,
                    claimed_at=utcnow_naive(),
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("The no-show task was claimed concurrently")
            await session.commit()
            claimed = (task.id, task.task_key, task.task_type, task.payload, task.aggregate_key)

        await worker._process_claimed(claimed)

        async with factory() as session:
            reservation = await session.get(Reservation, reservation_id)
            task = await session.scalar(
                select(OutboxTask).where(OutboxTask.id == claimed[0])
            )
            penalty = await session.scalar(
                select(PenaltyCase).where(
                    PenaltyCase.reservation_id == reservation_id,
                    PenaltyCase.violation_type == "NO_SHOW",
                )
            )
            if reservation is None or reservation.status != "NO_SHOW":
                raise RuntimeError("The worker did not transition the reservation to NO_SHOW")
            if task is None or task.status != "COMPLETED":
                raise RuntimeError("The worker did not complete the no-show outbox task")
            if penalty is None:
                raise RuntimeError("The active college policy did not create a penalty")
            print(
                json.dumps(
                    {
                        "reservation_id": reservation_id,
                        "reservation_status": reservation.status,
                        "outbox_status": task.status,
                        "penalty_case_id": penalty.id,
                        "violation_type": penalty.violation_type,
                        "points_delta": penalty.points_delta,
                        "reservation_block_days": penalty.reservation_block_days,
                        "scope_lab_id": penalty.lab_id,
                    }
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reservation_id", type=int)
    args = parser.parse_args()
    asyncio.run(run(args.reservation_id))
