"""Exercise HTTP upload -> SQL Outbox -> Redis -> live Celery Worker -> Qdrant.

Run from backend/ after MySQL, Redis, and Qdrant are available and the current
Alembic head is applied:

    uv run python scripts/smoke_knowledge_build_worker.py

The script uses a temporary Qdrant collection, deterministic test Embeddings,
and a dependency-overridden lab manager. It does not call paid model APIs.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from collections import deque
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pymupdf
import uvicorn
from app.ai.config import get_component_config
from app.ai.rag.hybrid import hybrid_search
from app.ai.rag.qdrant_store import QdrantKnowledgeStore
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import get_settings
from app.infrastructure.db.models import (
    AiAuxUsageEvent,
    College,
    KnowledgeDocument,
    OutboxTask,
    UploadAsset,
    User,
)
from app.infrastructure.db.session import build_engine, build_session_factory
from app.infrastructure.tasks.worker import OutboxWorker
from app.main import create_app
from qdrant_client import AsyncQdrantClient
from sqlalchemy import delete


def _make_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "Laboratory equipment reservation. Check the safety interlock before use.",
        )
        document.save(path)


async def _drain_worker_output(
    process: asyncio.subprocess.Process,
    ready: asyncio.Event,
    lines: deque[str],
) -> None:
    assert process.stdout is not None
    while line := await process.stdout.readline():
        decoded = line.decode("utf-8", errors="replace").rstrip()
        lines.append(decoded)
        if " ready." in decoded or decoded.endswith(" ready."):
            ready.set()


async def _wait_for_server(server: uvicorn.Server) -> int:
    for _ in range(300):
        if server.started and server.servers:
            sockets = server.servers[0].sockets
            if sockets:
                return int(sockets[0].getsockname()[1])
        await asyncio.sleep(0.05)
    raise RuntimeError("Uvicorn did not start within 15 seconds")


async def run() -> None:
    base = get_settings()
    suffix = uuid4().hex[:10]
    collection = f"knowledge_build_it_{suffix}"
    upload_dir = Path(tempfile.mkdtemp(prefix="knowledge-build-it-"))
    settings = base.model_copy(
        update={
            "environment": "test",
            "debug": False,
            "enable_workers": False,
            "ai_api_key": None,
            "ai_embedding_api_key": None,
            "ai_mineru_api_key": None,
            "ai_qdrant_collection": collection,
            "upload_dir": str(upload_dir),
            "ai_knowledge_build_embed_batch_size": 2,
            "celery_worker_concurrency": 1,
        }
    )
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    worker_process: asyncio.subprocess.Process | None = None
    worker_reader: asyncio.Task[None] | None = None
    outbox_worker: OutboxWorker | None = None
    server_task: asyncio.Task[None] | None = None
    qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=10)
    document_id: int | None = None
    job_id: str | None = None
    user_id: int | None = None
    college_id: int | None = None
    upload_token: str | None = None

    try:
        async with factory() as session, session.begin():
            college = College(code=f"IT-{suffix}", name=f"Knowledge build IT {suffix}")
            session.add(college)
            await session.flush()
            user = User(
                username=f"knowledge-it-{suffix}",
                password_hash="integration-smoke-only",
                real_name="Knowledge build smoke test",
                user_type="STUDENT",
                college_id=college.id,
                status=1,
            )
            session.add(user)
            await session.flush()
            college_id = int(college.id)
            user_id = int(user.id)

        principal = Principal(
            user_id=user_id,
            username=f"knowledge-it-{suffix}",
            college_id=college_id,
            roles=("LAB_ADMIN",),
            token_type="access",
            token_id=f"knowledge-build-integration-{suffix}",
            permissions=("ai:use", "ai:knowledge:manage"),
        )
        app = create_app(settings)
        app.state.db_engine = engine
        app.state.session_factory = factory
        app.state.metrics.monitor_sqlalchemy_pool(engine)

        async def override_principal() -> Principal:
            return principal

        async def no_csrf() -> None:
            return None

        app.dependency_overrides[get_current_principal] = override_principal
        app.dependency_overrides[enforce_csrf] = no_csrf

        celery_env = os.environ.copy()
        celery_env.update(
            {
                "LAB_ENVIRONMENT": "test",
                "LAB_ENABLE_WORKERS": "false",
                "LAB_MYSQL_DSN": settings.mysql_dsn,
                "LAB_REDIS_URL": settings.redis_url,
                "LAB_CELERY_BROKER_URL": settings.celery_broker_url,
                "LAB_QDRANT_URL": settings.qdrant_url,
                "LAB_AI_QDRANT_COLLECTION": collection,
                "LAB_UPLOAD_DIR": str(upload_dir),
                "LAB_AI_API_KEY": "",
                "LAB_AI_EMBEDDING_API_KEY": "",
                "LAB_AI_MINERU_API_KEY": "",
                "LAB_CELERY_WORKER_CONCURRENCY": "1",
            }
        )
        worker_process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.infrastructure.tasks.celery_app:celery_app",
            "worker",
            "--loglevel=INFO",
            "--pool=solo",
            "--concurrency=1",
            "--prefetch-multiplier=1",
            "--queues=knowledge-build",
            "--without-gossip",
            "--without-mingle",
            cwd=Path.cwd(),
            env=celery_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        worker_ready = asyncio.Event()
        worker_lines: deque[str] = deque(maxlen=100)
        worker_reader = asyncio.create_task(
            _drain_worker_output(worker_process, worker_ready, worker_lines)
        )
        try:
            await asyncio.wait_for(worker_ready.wait(), timeout=45)
        except TimeoutError as exc:
            raise RuntimeError(
                "Celery Worker did not become ready; recent output: " + " | ".join(worker_lines)
            ) from exc

        outbox_worker = OutboxWorker(app, poll_seconds=0.2)
        await outbox_worker.start()
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=0,
                loop="asyncio",
                lifespan="off",
                log_level="warning",
                access_log=False,
            )
        )
        server_task = asyncio.create_task(server.serve())
        port = await _wait_for_server(server)
        base_url = f"http://127.0.0.1:{port}"

        source = upload_dir / "smoke-guide.pdf"
        _make_pdf(source)
        pdf_bytes = source.read_bytes()
        started = asyncio.get_running_loop().time()
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{base_url}/api/v2/ai/knowledge/upload",
                data={"title": f"Build smoke {suffix}", "source_type": "SOP"},
                files={"file": ("smoke-guide.pdf", pdf_bytes, "application/pdf")},
            )
            upload_seconds = asyncio.get_running_loop().time() - started
            if response.status_code != 202:
                raise RuntimeError(f"Upload returned {response.status_code}: {response.text}")
            accepted = response.json()["data"]
            document_id = int(accepted["document_id"])
            job_id = str(accepted["job_id"])
            task_id = str(accepted["task_id"])
            if upload_seconds > 5:
                raise RuntimeError(f"Upload took {upload_seconds:.2f}s before build completion")

            deadline = asyncio.get_running_loop().time() + 90
            status_data: dict[str, object] = {}
            while asyncio.get_running_loop().time() < deadline:
                status_response = await client.get(
                    f"{base_url}/api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}"
                )
                status_response.raise_for_status()
                status_data = status_response.json()["data"]
                if status_data["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                    break
                await asyncio.sleep(0.25)
            if status_data.get("status") != "COMPLETED":
                diagnostics = [line for line in worker_lines if "knowledge build" in line.lower()]
                raise RuntimeError(
                    f"Build did not complete: {status_data}; worker diagnostics: {diagnostics}"
                )

            detail = await client.get(f"{base_url}/api/v2/ai/knowledge/{document_id}")
            detail.raise_for_status()
            extracted_text = detail.json()["data"]["extracted_text"]
            if not extracted_text or "Laboratory equipment reservation" not in extracted_text:
                raise RuntimeError("PyMuPDF text was not persisted to the knowledge document")

            review = await client.put(
                f"{base_url}/api/v2/ai/knowledge/{document_id}/review",
                json={"reviewed_text": extracted_text},
            )
            review.raise_for_status()
            publish = await client.post(f"{base_url}/api/v2/ai/knowledge/{document_id}/publish")
            publish.raise_for_status()

        async with factory() as session:
            runtime = await get_component_config(session, settings, "embedding")
        store = QdrantKnowledgeStore(settings, runtime)
        try:
            async with factory() as session:
                hits = await hybrid_search(
                    session,
                    store,
                    "equipment safety interlock",
                    principal,
                    3,
                )
        finally:
            await store.close()
        if not any(hit.document_id == document_id for hit in hits):
            raise RuntimeError("Published document was not returned by live Qdrant hybrid search")

        print(
            "INTEGRATION_OK "
            f"http_status=202 upload_seconds={upload_seconds:.3f} "
            f"job_id={job_id} task_id={task_id} status={status_data['status']} "
            f"stage={status_data['stage']} chunks_found={len(hits)}"
        )
    finally:
        if outbox_worker is not None:
            await outbox_worker.stop()
        if server_task is not None:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=10)
        if worker_process is not None and worker_process.returncode is None:
            worker_process.terminate()
            try:
                await asyncio.wait_for(worker_process.wait(), timeout=10)
            except TimeoutError:
                worker_process.kill()
                await worker_process.wait()
        if worker_reader is not None:
            await asyncio.gather(worker_reader, return_exceptions=True)
        if user_id is not None:
            async with factory() as session, session.begin():
                if document_id is not None:
                    await session.execute(
                        delete(OutboxTask).where(
                            OutboxTask.aggregate_key == f"ai-knowledge:{document_id}"
                        )
                    )
                    await session.execute(
                        delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
                    )
                if job_id is not None:
                    await session.execute(
                        delete(AiAuxUsageEvent).where(
                            AiAuxUsageEvent.event_key.like(f"knowledge-build:{job_id}:%")
                        )
                    )
                await session.execute(delete(UploadAsset).where(UploadAsset.user_id == user_id))
                await session.execute(delete(User).where(User.id == user_id))
                if college_id is not None:
                    await session.execute(delete(College).where(College.id == college_id))
        try:
            if await qdrant.collection_exists(collection):
                await qdrant.delete_collection(collection)
        finally:
            await qdrant.close()
            await engine.dispose()
            if "app" in locals():
                app.dependency_overrides.clear()
            import shutil

            shutil.rmtree(upload_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run())
