"""Runtime configuration shared by the new QA assets; secrets are never logged."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "qa_eval" / "results"
BASE_URL = os.getenv("QA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MYSQL_DSN = os.getenv("QA_MYSQL_DSN", "")
REDIS_URL = os.getenv("QA_REDIS_URL", "redis://127.0.0.1:6379/0")
FIXTURE_FILE = Path(os.getenv("QA_FIXTURE_FILE", str(RESULTS / "fixture.json")))


def require_mysql_dsn() -> str:
    if not MYSQL_DSN:
        raise RuntimeError("Set QA_MYSQL_DSN to a disposable local MySQL schema DSN")
    return MYSQL_DSN

