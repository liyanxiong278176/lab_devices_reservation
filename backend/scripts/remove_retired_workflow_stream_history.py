"""Remove retired module events after Flyway V5, retaining all other notification streams."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.settings import Settings
from app.infrastructure.db.session import build_engine
from redis.asyncio import Redis
from sqlalchemy import text

RETIRED = {
    "PENALTY",
    "PENALTY_CASE",
    "PENALTY_APPEAL",
    "OVERDUE",
    "MAINTENANCE",
    "MAINTENANCE_PLAN",
    "MAINTENANCE_RECORD",
}


async def main():
    settings = Settings()
    engine = build_engine(settings)
    try:
        async with engine.connect() as connection:
            version = (
                await connection.execute(
                    text(
                        "SELECT COUNT(*) FROM flyway_schema_history WHERE version='5' AND success=1"
                    )
                )
            ).scalar_one()
            if version != 1:
                raise RuntimeError("Apply Flyway V5 before purging retired workflow events")
    finally:
        await engine.dispose()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    counts = {}
    try:
        for stream in ("lab:v2:notification:events", "lab:v2:notification:dead-letter"):
            start, deleted = "-", 0
            while True:
                rows = await redis.xrange(stream, min=start, max="+", count=200)
                if not rows:
                    break
                ids = []
                for identifier, values in rows:
                    payload = json.loads(values.get("payload", "{}"))
                    notification = payload.get("notification", payload)
                    key = values.get("source_task_key", "")
                    if (
                        notification.get("relatedType", notification.get("related_type")) in RETIRED
                        or key.startswith(("notification:penalty:", "notification:overdue:"))
                        or key.endswith(":no-show")
                    ):
                        ids.append(identifier)
                if ids:
                    deleted += await redis.xdel(stream, *ids)
                start = "(" + rows[-1][0]
            counts[stream] = deleted
    finally:
        await redis.aclose()
    print(json.dumps({"removedRealtimeHistory": counts}))


if __name__ == "__main__":
    asyncio.run(main())
