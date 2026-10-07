"""Deployment entry point: initial sample inventory, without demo credentials."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import Settings
from app.infrastructure.db.bootstrap import ensure_bootstrap_admin
from app.infrastructure.db.catalog_bootstrap import seed_initial_catalog
from app.infrastructure.db.session import build_engine, build_session_factory


async def main() -> None:
    settings = Settings()
    engine = build_engine(settings)
    try:
        # Existing administrator accounts/passwords are never overwritten.
        await ensure_bootstrap_admin(build_session_factory(engine), settings)
        counts = await seed_initial_catalog(
            engine, admin_username=settings.bootstrap_admin_username
        )
        print(json.dumps({"catalog_initialization": counts}, ensure_ascii=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
