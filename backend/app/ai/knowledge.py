from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.ai.config import get_component_config
from app.ai.dlp import redact_text
from app.ai.usage import add_aux_usage
from app.infrastructure.db.models import KnowledgeDocument, OutboxTask
from app.infrastructure.db.session import build_session_factory

MINERU_API = "https://mineru.net"
MINERU_RESULT_HOSTS = {"cdn-mineru.openxlab.org.cn"}
MINERU_UPLOAD_HOSTS = {"mineru.oss-cn-shanghai.aliyuncs.com"}
MAX_RESULT_ZIP_BYTES = 50 * 1024 * 1024
MAX_MARKDOWN_CHARS = 500_000


def _is_allowed_mineru_upload_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return False
    return (
        host in MINERU_UPLOAD_HOSTS
        or host == "openxlab.org.cn"
        or host.endswith(".openxlab.org.cn")
    )


async def enqueue_parse_poll(
    session,
    *,
    document: KnowledgeDocument,
    batch_id: str,
    attempt: int,
) -> None:
    session.add(
        OutboxTask(
            task_key=f"ai-knowledge-poll:{document.id}:{batch_id}:{attempt}",
            task_type="AI_KNOWLEDGE_POLL",
            aggregate_key=f"ai-knowledge:{document.id}",
            college_id=document.college_id,
            payload={"document_id": document.id, "batch_id": batch_id, "attempt": attempt},
            status="PENDING",
            execute_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=5),
        )
    )


async def _reload_active_parse_document(session, document, batch_id: str) -> bool:
    """Serialize parser state updates with document deletion."""
    await session.refresh(document, with_for_update=True)
    return (
        document.status not in {"DELETING", "DELETED"}
        and document.parse_status == "PROCESSING"
        and document.mineru_task_id == batch_id
    )


async def start_mineru_parse(app, document_id: int) -> None:
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        from app.infrastructure.db.session import build_engine

        engine = build_engine(app.state.settings)
        app.state.db_engine = engine
        factory = build_session_factory(engine)
        app.state.session_factory = factory
    async with factory() as session:
        document = await session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )
        if (
            document is None
            or document.status in {"DELETING", "DELETED"}
            or document.parse_status not in {"QUEUED", "SUBMITTING"}
        ):
            return
        root = (Path(app.state.settings.upload_dir).resolve() / "ai-knowledge").resolve()
        path = Path(document.source_file_path or "").resolve()
        if not path.is_relative_to(root) or not path.is_file():
            document.parse_status = "FAILED"
            document.parse_error = "原始文件不存在或路径无效，请重新上传。"
            await session.commit()
            return
        key = await get_component_config(session, app.state.settings, "mineru")
        if key is None or not key.enabled or not key.api_key:
            raise RuntimeError("MinerU configuration is unavailable")
        document.parse_status = "SUBMITTING"
        await session.commit()
        file_name = document.source_file_name or path.name
        data_id = f"knowledge-{document.id}-v{document.version}"
        headers = {"Authorization": f"Bearer {key.api_key}"}
        timeout = httpx.Timeout(90.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(
                f"{MINERU_API}/api/v4/file-urls/batch",
                headers=headers,
                json={
                    "files": [{"name": file_name, "data_id": data_id}],
                    "model_version": key.model,
                    "enable_table": True,
                    "is_ocr": True,
                    "language": "ch",
                },
            )
            response.raise_for_status()
            result = response.json()
            data = result.get("data") or {}
            batch_id = data.get("batch_id")
            upload_urls = data.get("file_urls") or []
            if result.get("code") != 0 or not batch_id or not upload_urls:
                raise RuntimeError("MinerU upload request rejected")
            if not _is_allowed_mineru_upload_url(str(upload_urls[0])):
                raise RuntimeError("MinerU returned an invalid signed upload URL")
            upload = await client.put(str(upload_urls[0]), content=path.read_bytes())
            upload.raise_for_status()
        await session.refresh(document, with_for_update=True)
        if document.status in {"DELETING", "DELETED"} or document.parse_status != "SUBMITTING":
            return
        document.mineru_task_id = str(batch_id)
        document.parse_status = "PROCESSING"
        await enqueue_parse_poll(session, document=document, batch_id=str(batch_id), attempt=0)
        await session.commit()


async def poll_mineru_parse(app, document_id: int, batch_id: str, attempt: int) -> None:
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        from app.infrastructure.db.session import build_engine

        engine = build_engine(app.state.settings)
        app.state.db_engine = engine
        factory = build_session_factory(engine)
        app.state.session_factory = factory
    async with factory() as session:
        document = await session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.mineru_task_id == batch_id,
            )
        )
        if (
            document is None
            or document.status in {"DELETING", "DELETED"}
            or document.parse_status != "PROCESSING"
        ):
            return
        runtime = await get_component_config(session, app.state.settings, "mineru")
        if runtime is None or not runtime.enabled or not runtime.api_key:
            raise RuntimeError("MinerU configuration is unavailable")
        headers = {"Authorization": f"Bearer {runtime.api_key}"}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(
                f"{MINERU_API}/api/v4/extract-results/batch/{batch_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            data = result.get("data") or {}
            if result.get("code") != 0:
                raise RuntimeError("MinerU status query failed")
            result_items = data.get("extract_result") or []
            expected_id = f"knowledge-{document.id}-v{document.version}"
            item = next(
                (
                    row
                    for row in result_items
                    if row.get("data_id") == expected_id
                    or row.get("file_name") == document.source_file_name
                ),
                result_items[0] if len(result_items) == 1 else None,
            )
            if item is None:
                raise RuntimeError("MinerU result does not match the submitted document")
            state = str(item.get("state", ""))
            if state in {"waiting-file", "pending", "running", "converting"}:
                if not await _reload_active_parse_document(session, document, batch_id):
                    return
                if attempt >= 240:
                    document.parse_status = "FAILED"
                    document.parse_error = "文档解析超时，请稍后重新发起。"
                    await session.commit()
                    return
                await enqueue_parse_poll(
                    session,
                    document=document,
                    batch_id=batch_id,
                    attempt=attempt + 1,
                )
                await session.commit()
                return
            if state == "failed":
                if not await _reload_active_parse_document(session, document, batch_id):
                    return
                document.parse_status = "FAILED"
                document.parse_error = "MinerU 无法解析该文件，请检查文件内容后重试。"
                await session.commit()
                return
            if state != "done":
                raise RuntimeError("MinerU returned an unknown task state")
            result_url = urlparse(str(item.get("full_zip_url", "")))
            if result_url.scheme != "https" or result_url.hostname not in MINERU_RESULT_HOSTS:
                raise RuntimeError("MinerU returned an invalid result URL")
            zip_response = await client.get(str(item["full_zip_url"]))
            zip_response.raise_for_status()
            if len(zip_response.content) > MAX_RESULT_ZIP_BYTES:
                raise RuntimeError("MinerU result archive exceeds the size limit")
        markdown = _extract_markdown(zip_response.content)
        redaction = redact_text(markdown[:MAX_MARKDOWN_CHARS])
        if not await _reload_active_parse_document(session, document, batch_id):
            return
        document.extracted_text = redaction.text
        document.dlp_categories = sorted(
            set(document.dlp_categories or ()) | set(redaction.categories)
        )
        document.parse_status = "PARSED"
        document.parse_error = None
        source_path = Path(document.source_file_path or "")
        add_aux_usage(
            session,
            event_key=f"mineru:{document.id}:v{document.version}",
            component="mineru",
            operation="document_parse",
            model=runtime.model,
            user_id=document.created_by,
            college_id=document.college_id,
            item_count=int(item.get("page_count") or item.get("page_num") or 0),
            input_units=source_path.stat().st_size if source_path.is_file() else 0,
        )
        await session.commit()


def _extract_markdown(archive: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            matches = [
                item
                for item in bundle.infolist()
                if Path(item.filename).name == "full.md"
                and item.file_size <= MAX_MARKDOWN_CHARS * 4
            ]
            if not matches:
                raise ValueError("missing parsed markdown")
            return bundle.read(matches[0]).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise RuntimeError("MinerU returned an invalid Markdown archive") from exc
