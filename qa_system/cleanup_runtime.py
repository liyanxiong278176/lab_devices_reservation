"""Delete only the database, Redis index, and Qdrant collection in this run manifest."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from mysql_admin import execute as execute_mysql
from redis import Redis

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa_system"
PRIVATE_STATE = QA / ".runtime-secrets.json"
PUBLIC_STATE = QA / "results" / "runtime.json"


def main() -> int:
    if not PRIVATE_STATE.exists() or not PUBLIC_STATE.exists():
        raise RuntimeError("runtime manifest missing; refusing broad cleanup")
    private = json.loads(PRIVATE_STATE.read_text(encoding="utf-8"))
    public = json.loads(PUBLIC_STATE.read_text(encoding="utf-8"))
    schema = str(private.get("schema", ""))
    suffix = str(private.get("suffix", ""))
    collection = str(private.get("qdrant_collection", ""))
    database_user = str(private.get("mysql_user", ""))
    if (
        not suffix
        or schema != f"lab_reservation_qa_{suffix}"
        or database_user != f"qaeval_{suffix}"
        or collection != f"qaeval_{suffix}"
    ):
        raise RuntimeError(
            "runtime manifest does not match the safe QA naming rule; refusing cleanup"
        )
    if public.get("schema") != schema or public.get("qdrant_collection") != collection:
        raise RuntimeError("runtime manifests disagree; refusing cleanup")

    execute_mysql(
        f"DROP DATABASE IF EXISTS `{schema}`;\nDROP USER IF EXISTS '{database_user}'@'%';\n"
    )

    client = Redis.from_url(str(private["redis_url"]), socket_timeout=2)
    try:
        if client.ping():
            client.flushdb()
    finally:
        client.close()

    try:
        import sys

        from qdrant_client import QdrantClient

        sys.path.insert(0, str(ROOT / "backend"))
        old_directory = Path.cwd()
        os.chdir(ROOT / "backend")
        try:
            from app.core.settings import Settings

            qdrant_url = Settings().qdrant_url
        finally:
            os.chdir(old_directory)
        qdrant = QdrantClient(url=qdrant_url, timeout=5)
        if qdrant.collection_exists(collection):
            qdrant.delete_collection(collection)
        qdrant.close()
    except Exception as exc:
        raise RuntimeError("Qdrant cleanup failed; database and Redis cleanup completed") from exc

    for path in (
        PRIVATE_STATE,
        PUBLIC_STATE,
        QA / "results" / "accounts.local.json",
        QA / "results" / "seed_ids.json",
    ):
        if path.exists():
            path.unlink()
    upload_root = (QA / ".uploads").resolve()
    qa_root = QA.resolve()
    if upload_root.parent == qa_root and upload_root.exists():
        shutil.rmtree(upload_root)
    print(
        f"Removed isolated QA schema and Redis DB {private['redis_database']}; "
        f"removed collection {collection}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Cleanup incomplete: {exc}", file=sys.stderr)
        raise SystemExit(2)
