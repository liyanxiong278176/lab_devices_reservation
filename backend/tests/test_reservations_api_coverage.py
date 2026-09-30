from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    Device,
    Reservation,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    Role,
    UploadAsset,
    User,
)
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

STUDENT_PERMISSIONS = (
    "device:read",
    "reservation:create",
    "reservation:read:own",
    "reservation:cancel",
    "reservation:check-in",
    "reservation:return",
)
MANAGER_PERMISSIONS = (
    "device:read",
    "reservation:read:scope",
    "reservation:approve",
    "reservation:handover",
    "reservation:accept-return",
    "reservation:cancel",
    "reservation:approve",
)


def _principal(user: User, role: str) -> Principal:
    permissions = STUDENT_PERMISSIONS if role == "STUDENT" else MANAGER_PERMISSIONS
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=(role,),
        token_type="access",
        token_id=f"reservation-api-{user.id}",
        permissions=permissions,
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(
            environment="test",
            mysql_dsn="sqlite+aiosqlite:///:memory:",
            cors_origins=["http://test"],
            redis_url="redis://127.0.0.1:6379/15",
            rate_limit_enabled=False,
        )
    )

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_actor() -> Principal:
        return actor["value"]

    async def no_csrf() -> None:
        return None

    async def no_rate_limit() -> None:
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_actor
    app.dependency_overrides[enforce_csrf] = no_csrf
    app.dependency_overrides[enforce_authenticated_rate_limit] = no_rate_limit
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _plan(device_id: int, start: date, end: date | None = None) -> dict[str, object]:
    return {
        "device_id": device_id,
        "start_date": start.isoformat(),
        "end_date": (end or start).isoformat(),
        "purpose": "接口链路覆盖验证",
    }


async def _add_image(session: AsyncSession, user: User, token: str) -> str:
    session.add(
        UploadAsset(
            asset_token=token,
            user_id=user.id,
            college_id=user.college_id,
            original_name="evidence.png",
            content_type="image/png",
            size_bytes=128,
            storage_path=f"memory://{token}",
        )
    )
    await session.commit()
    return f"/api/v2/repair-uploads/{token}"


@pytest.mark.asyncio
async def test_reservation_preflight_create_idempotency_listing_detail_and_cancel(seeded) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _ = seeded
    actor = {"value": _principal(student, "STUDENT")}
    requested = date.today() + timedelta(days=3)
    async with _client(factory, actor) as client:
        preflight = await client.post(
            "/api/v2/reservations/preflight",
            json=_plan(device.id, requested, requested + timedelta(days=1)),
        )
        assert preflight.status_code == 200
        assert preflight.json()["data"]["all_available"] is True

        payload = _plan(device.id, requested, requested + timedelta(days=1))
        created = await client.post(
            "/api/v2/reservations",
            json=payload,
            headers={"Idempotency-Key": "coverage-reservation-create-01"},
        )
        assert created.status_code == 201
        row = created.json()["data"]["created"][0]
        reservation_id = row["id"]
        assert row["user_id"] == student.id
        assert row["dates"] == [requested.isoformat(), (requested + timedelta(days=1)).isoformat()]

        replay = await client.post(
            "/api/v2/reservations",
            json=payload,
            headers={"Idempotency-Key": "coverage-reservation-create-01"},
        )
        assert replay.status_code == 201
        assert replay.json()["data"]["created"][0]["id"] == reservation_id

        reused = await client.post(
            "/api/v2/reservations",
            json={**payload, "purpose": "同一幂等键更换请求体"},
            headers={"Idempotency-Key": "coverage-reservation-create-01"},
        )
        assert reused.status_code == 409
        assert reused.json()["code"] == "IDEMPOTENCY_REUSED"

        listed = await client.get("/api/v2/reservations/mine?page=1&page_size=5&status=APPROVED")
        assert listed.status_code == 200
        assert listed.json()["data"]["total"] == 1
        detail = await client.get(f"/api/v2/reservations/{reservation_id}")
        assert detail.status_code == 200
        assert detail.json()["data"]["device_id"] == device.id

        cancelled = await client.post(f"/api/v2/reservations/{reservation_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "CANCELLED"

        after_cancel = await client.get("/api/v2/reservations/mine?status=CANCELLED")
        assert after_cancel.status_code == 200
        assert after_cancel.json()["data"]["items"][0]["id"] == reservation_id

    async with factory() as session:
        persisted = await session.get(Reservation, reservation_id)
        assert persisted is not None
        assert persisted.college_id == college.id
        assert persisted.status == "CANCELLED"


@pytest.mark.asyncio
async def test_approval_queue_single_batch_approval_and_rejection_routes(seeded) -> None:
    factory, _college, _other_college, student, _other_student, manager, device, _ = seeded
    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None
        stored_device.need_approval = True
        await session.commit()

    student_actor = {"value": _principal(student, "STUDENT")}
    base = date.today() + timedelta(days=2)
    ids: list[int] = []
    async with _client(factory, student_actor) as client:
        for offset in range(3):
            result = await client.post(
                "/api/v2/reservations",
                json=_plan(device.id, base + timedelta(days=offset)),
            )
            assert result.status_code == 201
            ids.append(result.json()["data"]["created"][0]["id"])

    manager_actor = {"value": _principal(manager, "LAB_ADMIN")}
    async with _client(factory, manager_actor) as client:
        pending = await client.get("/api/v2/approvals/pending?page=1&page_size=10")
        assert pending.status_code == 200
        assert {row["id"] for row in pending.json()["data"]["items"]} >= set(ids)

        approved = await client.post(f"/api/v2/approvals/{ids[0]}/approve")
        assert approved.status_code == 200
        assert approved.json()["data"]["status"] == "APPROVED"

        rejected = await client.post(
            f"/api/v2/approvals/{ids[1]}/reject",
            json={"reason": "用途与实验室安排冲突"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["data"]["status"] == "REJECTED"
        assert rejected.json()["data"]["reject_reason"] == "用途与实验室安排冲突"

        batch = await client.post("/api/v2/approvals/batch-approve", json={"ids": [ids[2]]})
        assert batch.status_code == 200
        assert batch.json()["data"]["approved"] == 1

        pending_after = await client.get("/api/v2/approvals/pending")
        assert pending_after.status_code == 200
        assert all(row["id"] not in ids for row in pending_after.json()["data"]["items"])


@pytest.mark.asyncio
async def test_same_day_handover_return_and_acceptance_routes(seeded) -> None:
    factory, _college, _other_college, student, other_student, manager, device, _ = seeded
    async with factory() as session:
        handover_url = await _add_image(session, manager, "reservation-api-handover-evidence-01")
        return_url = await _add_image(session, student, "reservation-api-return-evidence-01")

    student_actor = {"value": _principal(student, "STUDENT")}
    async with _client(factory, student_actor) as client:
        created = await client.post("/api/v2/reservations", json=_plan(device.id, date.today()))
        assert created.status_code == 201
        reservation_id = created.json()["data"]["created"][0]["id"]

        student_actor["value"] = _principal(other_student, "STUDENT")
        foreign_owner = await client.post(f"/api/v2/reservations/{reservation_id}/check-in")
        assert foreign_owner.status_code == 403

        student_actor["value"] = Principal(
            user_id=student.id,
            username=student.username,
            college_id=student.college_id,
            roles=("STUDENT",),
            token_type="access",
            token_id="reservation-check-in-no-permission",
            permissions=tuple(
                code for code in STUDENT_PERMISSIONS if code != "reservation:check-in"
            ),
        )
        no_permission = await client.post(f"/api/v2/reservations/{reservation_id}/check-in")
        assert no_permission.status_code == 403

        student_actor["value"] = _principal(student, "STUDENT")
        handovers = await client.post(f"/api/v2/reservations/{reservation_id}/check-in")
        assert handovers.status_code == 409
        assert handovers.json()["code"] == "HANDOVER_REQUIRED"

    manager_actor = {"value": _principal(manager, "LAB_ADMIN")}
    async with _client(factory, manager_actor) as client:
        pending = await client.get("/api/v2/reservations/handovers?status=PENDING")
        assert pending.status_code == 200
        assert reservation_id in {row["id"] for row in pending.json()["data"]["items"]}
        handed_over = await client.post(
            f"/api/v2/reservations/{reservation_id}/handover",
            json={"condition": "NORMAL", "image_urls": [handover_url], "checklist": []},
        )
        assert handed_over.status_code == 200
        assert handed_over.json()["data"]["status"] == "IN_USE"
        assert handed_over.json()["data"]["handover_status"] == "HANDED_OVER"

    student_actor["value"] = _principal(student, "STUDENT")
    async with _client(factory, student_actor) as client:
        returned = await client.post(
            f"/api/v2/reservations/{reservation_id}/return",
            json={"condition": "NORMAL", "note": "设备外观完好", "image_urls": [return_url]},
        )
        assert returned.status_code == 200
        assert returned.json()["data"]["handover_status"] == "RETURN_PENDING"

    manager_actor["value"] = _principal(manager, "LAB_ADMIN")
    async with _client(factory, manager_actor) as client:
        waiting = await client.get("/api/v2/reservations/handovers?status=RETURN_PENDING")
        assert waiting.status_code == 200
        assert reservation_id in {row["id"] for row in waiting.json()["data"]["items"]}
        accepted = await client.post(
            f"/api/v2/reservations/{reservation_id}/accept-return",
            json={"condition": "NORMAL", "note": "验收通过", "checklist": []},
        )
        assert accepted.status_code == 200
        assert accepted.json()["data"]["status"] == "COMPLETED"
        assert accepted.json()["data"]["handover_status"] == "RETURNED"


@pytest.mark.asyncio
async def test_waitlist_join_list_cancel_and_confirmation_routes(seeded) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _ = seeded
    target = date.today() + timedelta(days=5)
    student_actor = {"value": _principal(student, "STUDENT")}
    async with _client(factory, student_actor) as client:
        held = await client.post("/api/v2/reservations", json=_plan(device.id, target))
        assert held.status_code == 201

    async with factory() as session:
        student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
        assert student_role is not None
        waiter = User(
            username="reservation-waitlist-api-user",
            password_hash="test",
            real_name="候补用户",
            college_id=college.id,
            status=1,
            roles=[student_role],
        )
        session.add(waiter)
        await session.commit()
        await session.refresh(waiter)

    waiter_actor = {"value": _principal(waiter, "STUDENT")}
    async with _client(factory, waiter_actor) as client:
        joined = await client.post(
            "/api/v2/reservations/waitlist",
            json={
                "device_id": device.id,
                "reservation_date": target.isoformat(),
                "purpose": "设备冲突时排入候补",
            },
        )
        assert joined.status_code == 201
        entry_id = joined.json()["data"]["id"]

        duplicate = await client.post(
            "/api/v2/reservations/waitlist",
            json={
                "device_id": device.id,
                "reservation_date": target.isoformat(),
                "purpose": "重复候补申请",
            },
        )
        assert duplicate.status_code == 409

        mine = await client.get("/api/v2/reservations/waitlist/mine")
        assert mine.status_code == 200
        assert [row["id"] for row in mine.json()["data"]] == [entry_id]

        unavailable_offer = await client.post(
            "/api/v2/reservations/waitlist/999999/confirm"
        )
        assert unavailable_offer.status_code == 409

        cancelled = await client.delete(f"/api/v2/reservations/waitlist/{entry_id}")
        assert cancelled.status_code == 200
        assert cancelled.json()["data"] is None

        no_longer_listed = await client.get("/api/v2/reservations/waitlist/mine")
        assert no_longer_listed.status_code == 200
        assert no_longer_listed.json()["data"] == []

    async with factory() as session:
        entry = await session.get(ReservationWaitlist, entry_id)
        assert entry is not None
        assert entry.college_id == college.id
        assert entry.status == "CANCELLED"


@pytest.mark.asyncio
async def test_waitlist_offer_confirmation_releases_hold_then_creates_reservation(seeded) -> None:
    factory, college, _other_college, student, _other_student, _manager, device, _ = seeded
    target = date.today() + timedelta(days=6)
    student_actor = {"value": _principal(student, "STUDENT")}
    async with _client(factory, student_actor) as client:
        created = await client.post("/api/v2/reservations", json=_plan(device.id, target))
        reservation_id = created.json()["data"]["created"][0]["id"]

    async with factory() as session:
        entry = ReservationWaitlist(
            device_id=device.id,
            college_id=college.id,
            user_id=student.id,
            reservation_date=target,
            purpose="原预约取消后确认候补",
            status="OFFERED",
        )
        session.add(entry)
        await session.flush()
        session.add(
            ReservationWaitlistOffer(
                waitlist_id=entry.id,
                device_id=device.id,
                college_id=college.id,
                user_id=student.id,
                reservation_date=target,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5),
            )
        )
        await session.commit()
        entry_id = entry.id

    async with _client(factory, student_actor) as client:
        cancelled = await client.post(f"/api/v2/reservations/{reservation_id}/cancel")
        assert cancelled.status_code == 200
        confirmed = await client.post(f"/api/v2/reservations/waitlist/{entry_id}/confirm")
        assert confirmed.status_code == 200
        reservation = confirmed.json()["data"]["reservation"]
        assert reservation["user_id"] == student.id
        assert reservation["start_date"] == target.isoformat()

    async with factory() as session:
        entry = await session.get(ReservationWaitlist, entry_id)
        offer = await session.scalar(
            select(ReservationWaitlistOffer).where(
                ReservationWaitlistOffer.waitlist_id == entry_id
            )
        )
        assert entry is not None and entry.status == "CONFIRMED"
        assert offer is None


@pytest.mark.asyncio
async def test_handover_exception_cancellation_and_violation_routes(seeded) -> None:
    factory, _college, _other_college, student, _other_student, manager, device, _ = seeded
    async with factory() as session:
        image_url = await _add_image(session, manager, "reservation-api-damaged-handover-01")

    student_actor = {"value": _principal(student, "STUDENT")}
    async with _client(factory, student_actor) as client:
        exceptional = await client.post(
            "/api/v2/reservations",
            json=_plan(device.id, date.today()),
        )
        assert exceptional.status_code == 201
        exceptional_id = exceptional.json()["data"]["created"][0]["id"]

        violable = await client.post(
            "/api/v2/reservations",
            json=_plan(device.id, date.today() + timedelta(days=2)),
        )
        assert violable.status_code == 201
        violable_id = violable.json()["data"]["created"][0]["id"]

    manager_actor = {"value": _principal(manager, "LAB_ADMIN")}
    async with _client(factory, manager_actor) as client:
        exception = await client.post(
            f"/api/v2/reservations/{exceptional_id}/handover",
            json={
                "condition": "DAMAGED",
                "note": "交接时发现设备损坏",
                "image_urls": [image_url],
                "checklist": [],
            },
        )
        assert exception.status_code == 200
        assert exception.json()["data"]["status"] == "APPROVED"
        assert exception.json()["data"]["handover_status"] == "EXCEPTION"

        cancelled = await client.post(
            f"/api/v2/reservations/{exceptional_id}/cancel-handover-exception",
            json={"reason": "设备转维修，取消本次预约"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "CANCELLED"
        assert cancelled.json()["data"]["handover_status"] == "CANCELLED"

        violated = await client.post(
            f"/api/v2/reservations/{violable_id}/violate",
            json={"reason": "超出实验室使用规范"},
        )
        assert violated.status_code == 200
        assert violated.json()["data"]["status"] == "VIOLATED"
