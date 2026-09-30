from __future__ import annotations

import asyncio
import logging

from celery import Celery

from app.core.settings import get_settings

settings = get_settings()
celery_app = Celery(
    "lab_reservation",
    broker=settings.celery_broker_url,
    include=["app.infrastructure.tasks.celery_app"],
)
celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    broker_connection_timeout=5,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": settings.celery_visibility_timeout_seconds,
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
    },
    result_backend=None,
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.celery_worker_concurrency,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    task_default_queue="knowledge-build",
    task_default_routing_key="knowledge-build",
    task_routes={
        "app.infrastructure.tasks.celery_app.build_knowledge_document": {"queue": "knowledge-build"}
    },
)

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.infrastructure.tasks.celery_app.build_knowledge_document",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def build_knowledge_document(
    self,
    job_id: str,
    celery_task_id: str,
    order_token: int = 0,
) -> None:
    """Run one durable SQL-tracked document build; Celery state is not authoritative."""
    from app.ai.knowledge_build import (
        MAX_CELERY_RETRIES,
        PermanentBuildError,
        StaleBuildJob,
        TransientBuildError,
        is_transient_build_error,
        mark_build_cancelled,
        mark_build_failed,
        mark_build_retrying,
        process_knowledge_build_job,
    )

    active_settings = get_settings()
    try:
        # Accept the legacy argument during a rolling deployment; ordering is
        # now decided before publication by the SQL Outbox.
        _ = order_token
        asyncio.run(process_knowledge_build_job(active_settings, job_id, celery_task_id))
    except StaleBuildJob:
        asyncio.run(mark_build_cancelled(active_settings, job_id, celery_task_id))
        return
    except PermanentBuildError as exc:
        asyncio.run(mark_build_failed(active_settings, job_id, celery_task_id, exc, permanent=True))
        return
    except Exception as exc:
        if not isinstance(exc, TransientBuildError) and not is_transient_build_error(exc):
            asyncio.run(
                mark_build_failed(active_settings, job_id, celery_task_id, exc, permanent=True)
            )
            logger.error(
                "knowledge build crashed job_id=%s retries=%s error_type=%s",
                job_id,
                self.request.retries,
                type(exc).__name__,
            )
            raise
        retry_number = int(self.request.retries)
        if retry_number >= MAX_CELERY_RETRIES:
            asyncio.run(
                mark_build_failed(active_settings, job_id, celery_task_id, exc, permanent=False)
            )
            logger.error(
                "knowledge build retries exhausted job_id=%s retries=%s error_type=%s",
                job_id,
                retry_number,
                type(exc).__name__,
            )
            return
        asyncio.run(mark_build_retrying(active_settings, job_id, celery_task_id, exc))
        countdown = min(30 * (2**retry_number), 300)
        logger.warning(
            "knowledge build scheduled retry job_id=%s retry=%s countdown_seconds=%s error_type=%s",
            job_id,
            retry_number + 1,
            countdown,
            type(exc).__name__,
        )
        raise self.retry(exc=exc, countdown=countdown, max_retries=MAX_CELERY_RETRIES)
