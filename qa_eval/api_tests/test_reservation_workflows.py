from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from config import FIXTURE_FILE
from outbox_notification_worker import process_fixture_notifications

from conftest import occupied_day_count


def _reservation_body(device_id: int, start: date, end: date, purpose: str) -> dict[str, object]:
    return {
        "device_id": device_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "purpose": purpose,
    }


async def _upload_evidence(session, name: str) -> str:
    # The upload endpoint validates the PNG signature and persists a private
    # asset row. The payload is deliberately tiny and exists only for this QA run.
    png_signature = b"\x89PNG\r\n\x1a\n"
    uploaded = await session.client.post(
        "/api/v2/repair-uploads",
        files={"file": (name, png_signature, "image/png")},
        headers=session.headers(),
    )
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()["data"]["url"]


@pytest.mark.asyncio
async def test_date_validation_idempotency_overlap_and_adjacent_day(
    client_factory, manifest, mysql_factory
):
    student_a = await client_factory("student", "CSE")
    student_b = await client_factory("student", "CSE")
    device_id = manifest["device_ids"]["CSE"][1]  # no approval required
    day = date.today() + timedelta(days=12)

    invalid = await student_a.client.post(
        "/api/v2/reservations",
        json=_reservation_body(device_id, day + timedelta(days=1), day, "reversed dates"),
        headers=student_a.headers(),
    )
    assert invalid.status_code == 422

    empty_purpose = await student_a.client.post(
        "/api/v2/reservations",
        json=_reservation_body(device_id, day, day, ""),
        headers=student_a.headers(),
    )
    assert empty_purpose.status_code == 422

    request = _reservation_body(device_id, day, day, "idempotent same-day test")
    first = await student_a.client.post(
        "/api/v2/reservations",
        json=request,
        headers={
            **student_a.headers(),
            "Idempotency-Key": f"qa-eval-{manifest['run_id']}-idempotent",
        },
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["data"]["created"][0]["id"]
    assert first.json()["data"]["created"][0]["status"] == "APPROVED"

    replay = await student_a.client.post(
        "/api/v2/reservations",
        json=request,
        headers={
            **student_a.headers(),
            "Idempotency-Key": f"qa-eval-{manifest['run_id']}-idempotent",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["data"]["created"][0]["id"] == first_id
    assert await occupied_day_count(mysql_factory, device_id, day) == 1

    overlap = await student_b.client.post(
        "/api/v2/reservations",
        json=_reservation_body(device_id, day, day + timedelta(days=1), "overlapping interval"),
        headers={**student_b.headers(), "Idempotency-Key": f"qa-eval-{manifest['run_id']}-overlap"},
    )
    assert overlap.status_code == 409
    assert overlap.json()["code"] == "RESERVATION_CONFLICT"
    assert await occupied_day_count(mysql_factory, device_id, day + timedelta(days=1)) == 0

    adjacent = await student_b.client.post(
        "/api/v2/reservations",
        json=_reservation_body(
            device_id, day + timedelta(days=1), day + timedelta(days=1), "adjacent day"
        ),
        headers={
            **student_b.headers(),
            "Idempotency-Key": f"qa-eval-{manifest['run_id']}-adjacent",
        },
    )
    assert adjacent.status_code == 201, adjacent.text
    assert await occupied_day_count(mysql_factory, device_id, day + timedelta(days=1)) == 1


@pytest.mark.asyncio
async def test_max_days_past_page_bounds_and_query_injection_are_controlled(
    client_factory, manifest
):
    student = await client_factory("student", "CSE")
    device_id = manifest["device_ids"]["CSE"][1]
    today = date.today()

    overlong = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(
            device_id, today + timedelta(days=10), today + timedelta(days=18), "nine-day range"
        ),
        headers=student.headers(),
    )
    assert overlong.status_code == 422
    assert overlong.json()["code"] == "DATE_RANGE_TOO_LARGE"

    past = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(
            device_id, today - timedelta(days=1), today - timedelta(days=1), "past date"
        ),
        headers=student.headers(),
    )
    assert past.status_code == 422
    assert past.json()["code"] == "DATE_IN_PAST"

    page_zero = await student.client.get("/api/v2/reservations/mine?page=0&page_size=1")
    assert page_zero.status_code == 422
    page_one = await student.client.get("/api/v2/reservations/mine?page=1&page_size=1")
    assert page_one.status_code == 200
    deep_page = await student.client.get("/api/v2/reservations/mine?page=100002&page_size=1")
    assert deep_page.status_code == 422
    assert deep_page.json()["code"] == "PAGE_DEPTH_EXCEEDED"

    injected_search = await student.client.get(
        "/api/v2/devices",
        params={"search": "' OR '1'='1", "page": 1, "page_size": 20},
    )
    assert injected_search.status_code == 200
    assert injected_search.json()["data"]["total"] == 0
    script_search = await student.client.get(
        "/api/v2/devices",
        params={"search": "<script>alert(1)</script>", "page": 1, "page_size": 20},
    )
    assert script_search.status_code == 200
    assert script_search.json()["data"]["total"] == 0


@pytest.mark.asyncio
async def test_approval_handover_return_acceptance_and_notification_history(
    client_factory, manifest
):
    student = await client_factory("student", "CSE")
    manager = await client_factory("manager", "CSE")
    device_id = manifest["device_ids"]["CSE"][0]  # approval required
    today = date.today()

    created = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(device_id, today, today, "same-day full lifecycle"),
        headers={**student.headers(), "Idempotency-Key": f"qa-eval-{manifest['run_id']}-lifecycle"},
    )
    assert created.status_code == 201, created.text
    reservation = created.json()["data"]["created"][0]
    reservation_id = reservation["id"]
    assert reservation["status"] == "PENDING"
    manager_photo = await _upload_evidence(manager, "qa-handover.png")
    student_photo = await _upload_evidence(student, "qa-return.png")

    approved = await manager.client.post(
        f"/api/v2/approvals/{reservation_id}/approve",
        json={},
        headers=manager.headers(),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "APPROVED"

    # Product contract: the manager's physical handover is the start-use gate;
    # the legacy student self-check-in route must not bypass it.
    self_checkin = await student.client.post(
        f"/api/v2/reservations/{reservation_id}/check-in",
        headers=student.headers(),
    )
    assert self_checkin.status_code == 409
    assert self_checkin.json()["code"] == "HANDOVER_REQUIRED"

    handover = await manager.client.post(
        f"/api/v2/reservations/{reservation_id}/handover",
        json={
            "condition": "NORMAL",
            "note": "QA交接正常",
            "image_urls": [manager_photo],
            "checklist": [],
        },
        headers=manager.headers(),
    )
    assert handover.status_code == 200, handover.text
    assert handover.json()["data"]["status"] == "IN_USE"

    returned = await student.client.post(
        f"/api/v2/reservations/{reservation_id}/return",
        json={"condition": "NORMAL", "note": "QA归还正常", "image_urls": [student_photo]},
        headers=student.headers(),
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["data"]["handover_status"] == "RETURN_PENDING"

    accepted = await manager.client.post(
        f"/api/v2/reservations/{reservation_id}/accept-return",
        json={"condition": "NORMAL", "note": "QA验收正常", "checklist": []},
        headers=manager.headers(),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "COMPLETED"

    fixture_file = FIXTURE_FILE if FIXTURE_FILE.is_absolute() else Path.cwd() / FIXTURE_FILE
    await process_fixture_notifications(fixture_file)
    notifications = await student.client.get("/api/v2/notifications/mine?page=1&size=100")
    assert notifications.status_code == 200
    rows = notifications.json()["data"]["records"]
    reservation_rows = [row for row in rows if row["relatedId"] == reservation_id]
    assert {row["title"] for row in reservation_rows} >= {
        "预约申请已提交",
        "预约申请已通过",
        "设备已归还，等待验收",
    }


@pytest.mark.asyncio
async def test_rejection_cancellation_and_duplicate_state_transitions(
    client_factory, manifest, mysql_factory
):
    """Interface: reject/cancel release occupied dates and reject stale transitions."""
    student = await client_factory("student", "CSE")
    manager = await client_factory("manager", "CSE")
    start = date.today() + timedelta(days=20)
    rejected_device = manifest["device_ids"]["CSE"][0]
    cancelled_device = manifest["device_ids"]["CSE"][2]

    rejected = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(rejected_device, start, start, "rejection transition"),
        headers={**student.headers(), "Idempotency-Key": f"qa-eval-{manifest['run_id']}-reject"},
    )
    assert rejected.status_code == 201, rejected.text
    rejected_id = rejected.json()["data"]["created"][0]["id"]
    reject_response = await manager.client.post(
        f"/api/v2/approvals/{rejected_id}/reject",
        json={"reason": "QA rejection path"},
        headers=manager.headers(),
    )
    assert reject_response.status_code == 200, reject_response.text
    assert reject_response.json()["data"]["status"] == "REJECTED"
    duplicate_approval = await manager.client.post(
        f"/api/v2/approvals/{rejected_id}/approve", json={}, headers=manager.headers()
    )
    assert duplicate_approval.status_code == 409
    assert duplicate_approval.json()["code"] == "INVALID_RESERVATION_STATE"
    assert await occupied_day_count(mysql_factory, rejected_device, start) == 0

    cancelled = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(
            cancelled_device,
            start + timedelta(days=1),
            start + timedelta(days=1),
            "cancellation transition",
        ),
        headers={**student.headers(), "Idempotency-Key": f"qa-eval-{manifest['run_id']}-cancel"},
    )
    assert cancelled.status_code == 201, cancelled.text
    cancelled_id = cancelled.json()["data"]["created"][0]["id"]
    cancellation = await student.client.post(
        f"/api/v2/reservations/{cancelled_id}/cancel", headers=student.headers()
    )
    assert cancellation.status_code == 200, cancellation.text
    assert cancellation.json()["data"]["status"] == "CANCELLED"
    repeated_cancellation = await student.client.post(
        f"/api/v2/reservations/{cancelled_id}/cancel", headers=student.headers()
    )
    assert repeated_cancellation.status_code == 409
    assert repeated_cancellation.json()["code"] == "INVALID_RESERVATION_STATE"
    assert await occupied_day_count(mysql_factory, cancelled_device, start + timedelta(days=1)) == 0


@pytest.mark.asyncio
async def test_maintenance_device_cannot_be_reserved(client_factory, manifest, mysql_factory):
    """Integration: server-side device state blocks booking and leaves no occupied row."""
    from app.infrastructure.db.models import Device
    from sqlalchemy import update

    student = await client_factory("student", "CSE")
    device_id = manifest["device_ids"]["CSE"][5]
    day = date.today() + timedelta(days=23)
    async with mysql_factory() as session:
        await session.execute(
            update(Device).where(Device.id == device_id).values(status="MAINTENANCE")
        )
        await session.commit()
    try:
        response = await student.client.post(
            "/api/v2/reservations",
            json=_reservation_body(device_id, day, day, "must be rejected while under maintenance"),
            headers={
                **student.headers(),
                "Idempotency-Key": f"qa-eval-{manifest['run_id']}-maintenance",
            },
        )
        assert response.status_code == 409, response.text
        # The reservation API reports device-level unavailability through its
        # preflight conflict envelope, preserving the blocked date and reason.
        body = response.json()
        assert body["code"] == "RESERVATION_CONFLICT"
        assert body["data"]["conflicts"] == [
            {
                "date": day.isoformat(),
                "reason": "设备状态为 MAINTENANCE",
                "reservation_id": None,
                "status": None,
            }
        ]
        assert await occupied_day_count(mysql_factory, device_id, day) == 0
    finally:
        async with mysql_factory() as session:
            await session.execute(
                update(Device).where(Device.id == device_id).values(status="IDLE")
            )
            await session.commit()


@pytest.mark.asyncio
async def test_repair_requires_take_before_resolve_and_scopes_by_college(client_factory, manifest):
    student = await client_factory("student", "CSE")
    manager = await client_factory("manager", "CSE")
    bio_manager = await client_factory("manager", "BIO")
    device_id = manifest["device_ids"]["CSE"][3]
    foreign_device = manifest["device_ids"]["BIO"][3]

    foreign = await student.client.post(
        "/api/v2/repair-reports",
        json={
            "device_id": foreign_device,
            "title": "跨学院工单",
            "description": "tenant isolation",
        },
        headers=student.headers(),
    )
    assert foreign.status_code in (403, 404)

    created = await student.client.post(
        "/api/v2/repair-reports",
        json={
            "device_id": device_id,
            "title": "QA repair workflow",
            "description": "controlled test",
        },
        headers=student.headers(),
    )
    assert created.status_code == 201, created.text
    report_id = created.json()["data"]["id"]

    wrong_scope = await bio_manager.client.post(
        f"/api/v2/repair-reports/{report_id}/take", headers=bio_manager.headers()
    )
    assert wrong_scope.status_code in (403, 404)
    premature_resolve = await manager.client.post(
        f"/api/v2/repair-reports/{report_id}/resolve",
        json={"resolution_note": "should not resolve before taking"},
        headers=manager.headers(),
    )
    assert premature_resolve.status_code in (409, 422)

    taken = await manager.client.post(
        f"/api/v2/repair-reports/{report_id}/take", headers=manager.headers()
    )
    assert taken.status_code == 200, taken.text
    resolved = await manager.client.post(
        f"/api/v2/repair-reports/{report_id}/resolve",
        json={"resolution_note": "QA repair completed"},
        headers=manager.headers(),
    )
    assert resolved.status_code == 200, resolved.text
    confirm = await student.client.post(
        f"/api/v2/repair-reports/{report_id}/confirm",
        json={"confirmed": True, "note": "confirmed"},
        headers=student.headers(),
    )
    assert confirm.status_code == 200, confirm.text


@pytest.mark.asyncio
async def test_violation_and_no_show_release_days_and_write_credit_events(
    client_factory, manifest, mysql_factory
):
    """Integration: terminal penalties are persisted and release occupied device-days."""
    from app.core.settings import Settings
    from app.infrastructure.db import models
    from app.infrastructure.notifications.realtime import NotificationHub
    from app.infrastructure.tasks.worker import OutboxWorker, utcnow_naive
    from config import require_mysql_dsn
    from fastapi import FastAPI
    from sqlalchemy import func, select, update

    student = await client_factory("student", "CSE")
    manager = await client_factory("manager", "CSE")
    violation_device = manifest["device_ids"]["CSE"][1]  # approval is not required
    violation_day = date.today() + timedelta(days=10)
    violation_create = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(violation_device, violation_day, violation_day, "QA violation path"),
        headers={**student.headers(), "Idempotency-Key": f"qa-eval-{manifest['run_id']}-violation"},
    )
    assert violation_create.status_code == 201, violation_create.text
    violation_reservation = violation_create.json()["data"]["created"][0]
    assert violation_reservation["status"] == "APPROVED"
    async with mysql_factory() as session:
        credit_before = int(
            await session.scalar(
                select(models.User.credit_score).where(models.User.id == student.user_id)
            )
        )
    violated = await manager.client.post(
        f"/api/v2/reservations/{violation_reservation['id']}/violate",
        json={"reason": "QA verified violation"},
        headers=manager.headers(),
    )
    assert violated.status_code == 200, violated.text
    assert violated.json()["data"]["status"] == "VIOLATED"
    async with mysql_factory() as session:
        fresh_violation = await session.scalar(
            select(models.Reservation).where(models.Reservation.id == violation_reservation["id"])
        )
        credit_after_violation = int(
            await session.scalar(
                select(models.User.credit_score).where(models.User.id == student.user_id)
            )
        )
        violation_events = int(
            await session.scalar(
                select(func.count(models.CreditEvent.id)).where(
                    models.CreditEvent.reservation_id == violation_reservation["id"],
                    models.CreditEvent.event_type == "VIOLATION",
                    models.CreditEvent.points == -20,
                )
            )
            or 0
        )
    assert fresh_violation.status == "VIOLATED"
    assert credit_after_violation == credit_before - 20
    assert violation_events == 1
    assert await occupied_day_count(mysql_factory, violation_device, violation_day) == 0

    no_show_device = manifest["device_ids"]["CSE"][0]  # approval required
    no_show_day = date.today() + timedelta(days=7)
    no_show_create = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(no_show_device, no_show_day, no_show_day, "QA no-show path"),
        headers={**student.headers(), "Idempotency-Key": f"qa-eval-{manifest['run_id']}-no-show"},
    )
    assert no_show_create.status_code == 201, no_show_create.text
    no_show_id = no_show_create.json()["data"]["created"][0]["id"]
    approval = await manager.client.post(
        f"/api/v2/approvals/{no_show_id}/approve", json={}, headers=manager.headers()
    )
    assert approval.status_code == 200, approval.text

    task_key = f"timeout:reservation:{no_show_id}:no-show"
    async with mysql_factory() as session:
        task = await session.scalar(
            select(models.OutboxTask).where(models.OutboxTask.task_key == task_key)
        )
        assert task is not None and task.task_type == "RESERVATION_NO_SHOW"
        await session.execute(
            update(models.OutboxTask)
            .where(models.OutboxTask.id == task.id)
            .values(execute_at=utcnow_naive() - timedelta(seconds=1))
        )
        await session.commit()

    app = FastAPI()
    app.state.settings = Settings(
        environment="test", mysql_dsn=require_mysql_dsn(), enable_workers=False
    )
    app.state.notification_hub = NotificationHub()
    app.state.session_factory = mysql_factory
    worker = OutboxWorker(app, poll_seconds=0.05)
    claimed = await worker._claim_one(only_task_key=task_key)
    assert claimed is not None
    await worker._process_claimed(claimed)
    assert await worker._claim_one(only_task_key=task_key) is None

    async with mysql_factory() as session:
        fresh_no_show = await session.scalar(
            select(models.Reservation).where(models.Reservation.id == no_show_id)
        )
        no_show_events = int(
            await session.scalar(
                select(func.count(models.CreditEvent.id)).where(
                    models.CreditEvent.reservation_id == no_show_id,
                    models.CreditEvent.event_type == "NO_SHOW",
                    models.CreditEvent.points == -10,
                )
            )
            or 0
        )
        completed_task = await session.scalar(
            select(models.OutboxTask).where(models.OutboxTask.task_key == task_key)
        )
    assert fresh_no_show.status == "NO_SHOW"
    assert no_show_events == 1
    assert completed_task.status == "COMPLETED"
    assert await occupied_day_count(mysql_factory, no_show_device, no_show_day) == 0


@pytest.mark.asyncio
async def test_concurrent_approval_and_cancellation_has_one_winner(
    client_factory, manifest, mysql_factory
):
    """Integration: concurrent approve/cancel commits only one state transition."""
    from app.infrastructure.db import models
    from sqlalchemy import select

    student = await client_factory("student", "CSE")
    manager = await client_factory("manager", "CSE")
    device_id = manifest["device_ids"]["CSE"][0]
    day = date.today() + timedelta(days=11)
    created = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(device_id, day, day, "approve-cancel race"),
        headers={
            **student.headers(),
            "Idempotency-Key": f"qa-eval-{manifest['run_id']}-approve-cancel",
        },
    )
    assert created.status_code == 201, created.text
    reservation_id = created.json()["data"]["created"][0]["id"]

    approve, cancel = await asyncio.gather(
        manager.client.post(
            f"/api/v2/approvals/{reservation_id}/approve", json={}, headers=manager.headers()
        ),
        student.client.post(
            f"/api/v2/reservations/{reservation_id}/cancel", headers=student.headers()
        ),
    )
    assert sorted([approve.status_code, cancel.status_code]) == [200, 409]
    loser = approve if approve.status_code == 409 else cancel
    assert loser.json()["code"] in {"INVALID_RESERVATION_STATE", "RESERVATION_STATE_CHANGED"}
    async with mysql_factory() as session:
        persisted = await session.scalar(
            select(models.Reservation).where(models.Reservation.id == reservation_id)
        )
    assert persisted.status == ("APPROVED" if approve.status_code == 200 else "CANCELLED")
    occupied = await occupied_day_count(mysql_factory, device_id, day)
    assert occupied == (1 if approve.status_code == 200 else 0)


@pytest.mark.asyncio
async def test_two_outbox_workers_claim_once_and_notification_handler_is_idempotent(
    client_factory, manifest, mysql_factory
):
    """Integration: MySQL SKIP LOCKED elects one consumer and source_task_key deduplicates."""
    from app.core.settings import Settings
    from app.infrastructure.db import models
    from app.infrastructure.notifications.realtime import NotificationHub
    from app.infrastructure.tasks.worker import OutboxWorker
    from config import require_mysql_dsn
    from fastapi import FastAPI
    from sqlalchemy import func, select

    student = await client_factory("student", "CSE")
    async with mysql_factory() as session:
        previous_sequence = int(
            await session.scalar(
                select(func.max(models.Notification.delivery_sequence)).where(
                    models.Notification.user_id == student.user_id
                )
            )
            or 0
        )
    device_id = manifest["device_ids"]["CSE"][1]
    # Keep this exact device/date isolated from the earlier adjacent-day API case.
    day = date.today() + timedelta(days=27)
    created = await student.client.post(
        "/api/v2/reservations",
        json=_reservation_body(device_id, day, day, "QA Outbox race"),
        headers={
            **student.headers(),
            "Idempotency-Key": f"qa-eval-{manifest['run_id']}-outbox-race-{uuid.uuid4().hex}",
        },
    )
    assert created.status_code == 201, created.text
    reservation_id = created.json()["data"]["created"][0]["id"]
    task_key = f"notification:reservation:{reservation_id}:created"

    app = FastAPI()
    app.state.settings = Settings(
        environment="test", mysql_dsn=require_mysql_dsn(), enable_workers=False
    )
    app.state.notification_hub = NotificationHub()
    app.state.session_factory = mysql_factory
    first_worker = OutboxWorker(app, poll_seconds=0.05)
    second_worker = OutboxWorker(app, poll_seconds=0.05)
    claimed = await asyncio.gather(
        first_worker._claim_one(only_task_key=task_key),
        second_worker._claim_one(only_task_key=task_key),
    )
    winners = [
        (worker, item)
        for worker, item in zip((first_worker, second_worker), claimed, strict=True)
        if item
    ]
    if len(winners) != 1:
        async with mysql_factory() as session:
            outbox_state = await session.scalar(
                select(models.OutboxTask).where(models.OutboxTask.task_key == task_key)
            )
            blockers = list(
                (
                    await session.scalars(
                        select(models.OutboxTask).where(
                            models.OutboxTask.aggregate_key == f"reservation:{reservation_id}",
                            models.OutboxTask.status == "PROCESSING",
                            models.OutboxTask.id != (outbox_state.id if outbox_state else -1),
                        )
                    )
                ).all()
            )
        raise AssertionError(
            "expected exactly one local worker claim; "
            f"task_status={outbox_state.status if outbox_state else None}, "
            f"attempts={outbox_state.attempts if outbox_state else None}, "
            f"execute_at={outbox_state.execute_at if outbox_state else None}, "
            f"aggregate_blockers={len(blockers)}"
        )
    winning_worker, task = winners[0]
    assert (
        await (second_worker if winning_worker is first_worker else first_worker)._claim_one(
            only_task_key=task_key
        )
        is None
    )
    await winning_worker._process_claimed(task)

    # A worker may retry handler execution after a lost completion acknowledgement.
    # The deterministic source task key must find the same row, not create a duplicate.
    await winning_worker._handle(task[2], task[3], task_key)
    async with mysql_factory() as session:
        notification_count = int(
            await session.scalar(
                select(func.count(models.Notification.id)).where(
                    models.Notification.source_task_key == task_key
                )
            )
            or 0
        )
        notification = await session.scalar(
            select(models.Notification).where(models.Notification.source_task_key == task_key)
        )
        outbox = await session.scalar(
            select(models.OutboxTask).where(models.OutboxTask.task_key == task_key)
        )
    assert notification_count == 1
    assert notification is not None and notification.delivery_sequence == previous_sequence + 1
    assert outbox is not None and outbox.status == "COMPLETED"
