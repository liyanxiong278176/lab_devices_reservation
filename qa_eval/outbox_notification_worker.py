"""Drive only qa_eval recipients through the production OutboxWorker path.

The API server used for tests runs with ``LAB_ENVIRONMENT=test`` and therefore
does not start background workers. This narrow helper lets browser tests execute
their own persisted NOTIFICATION rows through the real claim, handler, and
completion logic without consuming unrelated user tasks or any AI task.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "qa_eval"))

from app.core.settings import Settings  # noqa: E402
from app.infrastructure.db.models import OutboxTask  # noqa: E402
from app.infrastructure.db.session import dispose_app_engine  # noqa: E402
from app.infrastructure.notifications.realtime import NotificationHub  # noqa: E402
from app.infrastructure.tasks.worker import OutboxWorker, utcnow_naive  # noqa: E402
from config import FIXTURE_FILE, require_mysql_dsn  # noqa: E402


async def process_fixture_notifications(manifest_path: Path) -> dict[str, int]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    qa_user_ids = sorted(
        {int(value) for group in manifest["student_ids"].values() for value in group}
    )
    settings = Settings(environment="test", mysql_dsn=require_mysql_dsn(), enable_workers=False)
    # A bare app state avoids running lifespan/bootstrap logic or importing
    # unrelated observability/AI startup dependencies from app.main.
    app = FastAPI()
    app.state.settings = settings
    app.state.notification_hub = NotificationHub()
    worker = OutboxWorker(app, poll_seconds=0.1)
    factory = await worker._session_factory()
    processed = 0
    inspected = 0
    deadline = time.monotonic() + 15

    try:
        while time.monotonic() < deadline:
            async with factory() as session:
                pending = list(
                    (
                        await session.scalars(
                            select(OutboxTask)
                            .where(
                                OutboxTask.task_type == "NOTIFICATION",
                                OutboxTask.status == "PENDING",
                                # Delayed reminders are valid pending tasks;
                                # the production worker cannot claim them yet.
                                # Only wait for currently due fixture messages.
                                OutboxTask.execute_at <= utcnow_naive(),
                                OutboxTask.payload["user_id"].as_integer().in_(qa_user_ids),
                            )
                            .order_by(OutboxTask.execute_at, OutboxTask.id)
                            .limit(100)
                        )
                    ).all()
                )
                keys = [task.task_key for task in pending]

            if not keys:
                return {"processed": processed, "inspected": inspected}

            claimed_any = False
            for task_key in keys:
                claimed = await worker._claim_one(only_task_key=task_key)
                if claimed is None:
                    continue
                claimed_any = True
                inspected += 1
                await worker._process_claimed(claimed)
                processed += 1

            if not claimed_any:
                await asyncio.sleep(0.1)

        raise TimeoutError("qa_eval NOTIFICATION tasks remained pending beyond 15 seconds")
    finally:
        await dispose_app_engine(app)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=FIXTURE_FILE)
    args = parser.parse_args()
    path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    result = asyncio.run(process_fixture_notifications(path))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
