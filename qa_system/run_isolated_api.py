"""Run the application against the disposable QA resources only."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa_system"
BACKEND = ROOT / "backend"
PRIVATE_STATE = QA / ".runtime-secrets.json"


def main() -> None:
    if not PRIVATE_STATE.exists():
        raise SystemExit("Run prepare_runtime.py first")
    secrets = json.loads(PRIVATE_STATE.read_text(encoding="utf-8"))
    fail_closed_mode = "--redis-fail-closed" in sys.argv[1:]
    performance_mode = "--performance" in sys.argv[1:]
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))

    from app.core.settings import Settings

    updates = {
        "mysql_dsn": secrets["mysql_dsn"],
        "redis_url": secrets["redis_url"],
        "environment": "local",
        # The QA schema is disposable; workers are needed to exercise the
        # durable AI_RUN and reservation outbox paths end to end.
        "enable_workers": "--no-workers" not in sys.argv[1:],
        "bootstrap_admin_username": secrets["admin_username"],
        "bootstrap_admin_password": secrets["admin_password"],
        "jwt_secret": secrets["jwt_secret"],
        "ai_api_key": "qa-mock-provider-key",
        "ai_base_url": "http://127.0.0.1:8765/v1",
        "ai_embedding_api_key": "qa-mock-provider-key",
        "ai_embedding_base_url": "http://127.0.0.1:8765/v1",
        "ai_qdrant_collection": secrets["qdrant_collection"],
        "cors_origins": ["http://127.0.0.1:5173", "http://localhost:5173"],
        "upload_dir": str(QA / ".uploads"),
    }
    if performance_mode:
        # Auth rate limiting has its own correctness suite; disable it only
        # when explicitly collecting throughput measurements in this schema.
        updates["rate_limit_enabled"] = False
    port = 8000
    if fail_closed_mode:
        updates.update(
            {
                "redis_url": f"redis://127.0.0.1:6399/{secrets['redis_database']}",
                "environment": "test",
                "rate_limit_enabled": False,
                "ai_provider_timeout_seconds": 2.0,
            }
        )
        port = 8001

    settings = Settings().model_copy(update=updates)
    import uvicorn
    from app.main import create_app

    application = create_app(settings)
    uvicorn.run(application, host="127.0.0.1", port=port, loop="asyncio")


if __name__ == "__main__":
    main()
