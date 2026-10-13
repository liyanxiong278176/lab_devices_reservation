"""Remove only project-owned AI resources before applying Flyway V2/V3.

Defaults to inspection. Business asset paths are protected; no AI archive is made.
Run during the write pause with the old API and Celery workers stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.settings import PROJECT_ROOT, Settings
from app.infrastructure.db.session import build_engine
from dotenv import dotenv_values
from redis.asyncio import from_url
from sqlalchemy import text


async def clean(
    apply: bool, stopped: bool, vector_url: str | None, broker_url: str | None, remove_config: bool
) -> None:
    if apply and not stopped:
        raise ValueError("--apply requires --old-processes-stopped during the write pause")
    settings = Settings()
    root = Path(settings.upload_dir)
    if not root.is_absolute():
        root = PROJECT_ROOT / "backend" / root
    root = root.resolve()
    dedicated = root / "ai-knowledge"
    protected: set[Path] = set()
    collections: set[str] = set()
    celery_ids: set[str] = set()
    engine = build_engine(settings)
    try:
        async with engine.connect() as connection:
            for row in await connection.execute(text("SELECT storage_path FROM v2_upload_asset")):
                value = Path(row[0])
                protected.add((value if value.is_absolute() else root / value.name).resolve())
            tables = set((await connection.execute(text("SHOW TABLES"))).scalars())
            if "v2_ai_knowledge_index_state" in tables:
                collections.update(
                    (
                        await connection.execute(
                            text(
                                "SELECT collection_name FROM v2_ai_knowledge_index_state "
                                "WHERE collection_name IS NOT NULL"
                            )
                        )
                    ).scalars()
                )
            if "v2_ai_embedding_rebuild_job" in tables:
                collections.update(
                    (
                        await connection.execute(
                            text(
                                "SELECT target_collection FROM v2_ai_embedding_rebuild_job "
                                "WHERE target_collection IS NOT NULL"
                            )
                        )
                    ).scalars()
                )
            if "v2_knowledge_build_job" in tables:
                celery_ids.update(
                    (
                        await connection.execute(
                            text(
                                "SELECT celery_task_id FROM v2_knowledge_build_job "
                                "WHERE celery_task_id IS NOT NULL"
                            )
                        )
                    ).scalars()
                )
    finally:
        await engine.dispose()
    configured = os.environ.get("LAB_AI_QDRANT_COLLECTION") or dotenv_values(
        PROJECT_ROOT / ".env"
    ).get("LAB_AI_QDRANT_COLLECTION")
    if configured:
        collections.add(configured)
    deleted = retained = 0
    if dedicated.exists():
        if dedicated.is_symlink() or dedicated.resolve().parent != root:
            raise ValueError("AI upload directory must stay inside the configured upload root")
        for file in dedicated.rglob("*"):
            if file.is_symlink():
                raise ValueError("AI directory contains a symbolic link; inspect it before cleanup")
            if file.is_file():
                if file.resolve() in protected:
                    retained += 1
                else:
                    deleted += 1
                    if apply:
                        file.unlink()
        if apply:
            for directory in sorted(
                (p for p in dedicated.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                if not any(directory.iterdir()):
                    directory.rmdir()
            if not any(dedicated.iterdir()):
                dedicated.rmdir()
    if vector_url:
        if not collections:
            raise ValueError(
                "No project collection ownership found; provide LAB_AI_QDRANT_COLLECTION explicitly"
            )
        from urllib.parse import quote, urlparse

        endpoint = urlparse(vector_url)
        if endpoint.scheme not in {"http", "https"} or endpoint.username or endpoint.query:
            raise ValueError("Invalid Qdrant endpoint")
        for collection in sorted(collections):
            if apply:
                request = Request(
                    vector_url.rstrip("/") + "/collections/" + quote(collection, safe=""),
                    method="DELETE",
                )
                try:
                    with urlopen(request, timeout=15) as response:
                        if response.status != 200:
                            raise RuntimeError("Qdrant collection deletion failed")
                except HTTPError as error:
                    if error.code != 404:
                        raise
    removed_keys = 0
    if broker_url:
        redis = from_url(broker_url, decode_responses=True)
        try:
            keys = {"knowledge-build", "_kombu.binding.knowledge-build"}
            keys.update("celery-task-meta-" + task_id for task_id in celery_ids)
            async for key in redis.scan_iter(match="knowledge-build*"):
                if key == "knowledge-build" or key.startswith("knowledge-build\x06\x16"):
                    keys.add(key)
            for key in keys:
                if await redis.exists(key):
                    removed_keys += 1
                    if apply:
                        await redis.unlink(key)
            # Other Celery queues, broker databases, sessions and business Streams stay intact.
            for task_key, raw in (await redis.hgetall("unacked")).items():
                value = json.loads(raw)
                if isinstance(value, list) and len(value) >= 3 and value[2] == "knowledge-build":
                    removed_keys += 1
                    if apply:
                        await redis.hdel("unacked", task_key)
                        await redis.zrem("unacked_index", task_key)
        finally:
            await redis.aclose()
    if apply and remove_config:
        config = PROJECT_ROOT / ".env"
        if config.exists():
            lines = config.read_text(encoding="utf-8").splitlines(keepends=True)
            config.write_text(
                "".join(
                    line
                    for line in lines
                    if not line.lstrip().startswith(("LAB_AI_", "LAB_QDRANT_", "LAB_CELERY_"))
                ),
                encoding="utf-8",
            )
    print(
        json.dumps(
            {
                "applied": apply,
                "aiFilesRemovedOrPlanned": deleted,
                "businessFilesRetained": retained,
                "projectVectorCollections": sorted(collections),
                "vectorDeletionRequested": bool(vector_url),
                "aiRedisKeysRemovedOrPlanned": removed_keys,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--old-processes-stopped", action="store_true")
    parser.add_argument("--vector-url")
    parser.add_argument("--broker-url")
    parser.add_argument("--remove-ai-config", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(
        clean(
            arguments.apply,
            arguments.old_processes_stopped,
            arguments.vector_url,
            arguments.broker_url,
            arguments.remove_ai_config,
        )
    )
