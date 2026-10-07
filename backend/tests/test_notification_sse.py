"""SSE notification tests, split by test layer.

Unit tests exercise the stream generator, sequence cursor, and in-process hub.
Interface tests drive the FastAPI GET route through HTTPX/ASGITransport.
The opt-in MySQL test verifies row-lock ordering across concurrent transactions;
SQLite is intentionally not treated as evidence for MySQL locking semantics.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from types import SimpleNamespace

import pytest
from app.api.v2 import notifications
from app.auth.security import Principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import Notification, User
from app.infrastructure.db.session import build_engine, build_session_factory
from app.infrastructure.notifications.realtime import NotificationHub
from app.infrastructure.notifications.sequence import next_delivery_sequence
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from scripts.e2e_fixture import cleanup, seed
from sqlalchemy import select
from starlette.requests import Request


def _request(
    app: FastAPI,
    *,
    origin: str | None = None,
    cookie: str | None = None,
) -> Request:
    headers = [(b"host", b"test")]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if cookie is not None:
        headers.append((b"cookie", cookie.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v2/notifications/stream",
        "raw_path": b"/api/v2/notifications/stream",
        "query_string": b"",
        "headers": headers,
        "client": ("192.0.2.50", 4567),
        "server": ("test", 80),
        "app": app,
    }
    return Request(scope)


def _principal(user_id: int, college_id: int, *, session_id: str = "session-1") -> Principal:
    return Principal(
        user_id=user_id,
        username=f"student-{user_id}",
        college_id=college_id,
        roles=(),
        token_type="access",
        token_id="test-token",
        permissions=("notification:read:own",),
        session_id=session_id,
    )


async def _insert_notifications(session, *, user_id: int, college_id: int, count: int) -> None:
    for index in range(count):
        sequence = await next_delivery_sequence(session, user_id)
        session.add(
            Notification(
                user_id=user_id,
                college_id=college_id,
                type="SYSTEM",
                title=f"通知 {index + 1}",
                content="SSE sequence test",
                delivery_sequence=sequence,
            )
        )
    await session.commit()


def _test_app(factory, *, replay_limit: int = 100) -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        _env_file=None,
        cors_origins=[],
        rate_limit_enabled=False,
        notification_sse_max_replay_events=replay_limit,
        notification_sse_heartbeat_seconds=5,
    )
    app.state.session_factory = factory
    app.state.notification_hub = NotificationHub()
    return app


async def _connected_stream(app: FastAPI, user_id: int) -> object:
    hub: NotificationHub = app.state.notification_hub
    stream = await hub.reserve_pending("192.0.2.50", max_pending=10, max_per_ip=10)
    assert stream is not None
    assert await hub.connect(user_id, stream, max_total=10, max_per_user=5, session_id="session-1")
    return stream


class _CloseAfterHandshakeHub(NotificationHub):
    """Bound interface-test streams after the response's initial SSE events."""

    async def wait(self, stream, timeout: float) -> bool:
        del timeout
        stream.closed.set()
        return True


def _interface_app(factory, *, principal: Principal) -> FastAPI:
    """Build a small FastAPI app for endpoint-contract tests without lifespan IO."""
    app = FastAPI()
    app.include_router(notifications.stream_router, prefix="/api/v2")
    app.state.settings = Settings(
        environment="test",
        _env_file=None,
        cors_origins=[],
        rate_limit_enabled=False,
        notification_sse_max_replay_events=100,
        notification_sse_heartbeat_seconds=5,
    )
    app.state.session_factory = factory
    app.state.notification_hub = _CloseAfterHandshakeHub()
    app.state.test_principal = principal
    return app


def _data(chunk: str) -> dict[str, object]:
    return json.loads(next(line[6:] for line in chunk.splitlines() if line.startswith("data: ")))


@pytest.mark.asyncio
async def test_user_delivery_sequence_advances_serially_within_a_transaction(seeded) -> None:
    factory, _, _, student, _, _, _, _ = seeded
    async with factory() as session:
        first = await next_delivery_sequence(session, student.id)
        session.add(
            Notification(
                user_id=student.id,
                college_id=student.college_id,
                type="SYSTEM",
                title="First",
                content="first",
                delivery_sequence=first,
            )
        )
        second = await next_delivery_sequence(session, student.id)
        assert (first, second) == (1, 2)


@pytest.mark.asyncio
async def test_new_eventsource_starts_at_current_head_without_replaying_history(seeded) -> None:
    factory, college, _, student, _, _, _, _ = seeded
    async with factory() as session:
        await _insert_notifications(session, user_id=student.id, college_id=college.id, count=2)
    app = _test_app(factory)
    stream = await _connected_stream(app, student.id)
    iterator = notifications._stream_events(
        _request(app), _principal(student.id, college.id), stream, None
    )

    comment = await anext(iterator)
    ready = await anext(iterator)

    assert comment == ": connected\n\n"
    assert "event: stream-ready" in ready
    assert "id: 2" in ready
    assert _data(ready) == {"replay": False}
    await iterator.aclose()


@pytest.mark.asyncio
async def test_last_event_id_replays_in_strict_user_sequence_order(seeded) -> None:
    factory, college, _, student, _, _, _, _ = seeded
    async with factory() as session:
        await _insert_notifications(session, user_id=student.id, college_id=college.id, count=4)
    app = _test_app(factory)
    stream = await _connected_stream(app, student.id)
    iterator = notifications._stream_events(
        _request(app), _principal(student.id, college.id), stream, 1
    )

    chunks = [await anext(iterator) for _ in range(7)]
    notification_chunks = [chunk for chunk in chunks if "event: notification" in chunk]
    sequence_ids = [
        int(next(line[4:] for line in chunk.splitlines() if line.startswith("id: ")))
        for chunk in notification_chunks
    ]

    assert sequence_ids == [2, 3, 4]
    assert "event: batch-complete" in chunks[-1]
    assert _data(chunks[-1]) == {
        "replay": True,
        "deliveredCount": 3,
        "omittedCount": 0,
        "historySyncRequired": False,
    }
    await iterator.aclose()


@pytest.mark.asyncio
async def test_stale_or_forged_cursor_is_clamped_to_the_visible_sequence_head(seeded) -> None:
    factory, college, _, student, _, _, _, _ = seeded
    async with factory() as session:
        await _insert_notifications(session, user_id=student.id, college_id=college.id, count=2)
    app = _test_app(factory)
    stream = await _connected_stream(app, student.id)
    iterator = notifications._stream_events(
        _request(app), _principal(student.id, college.id), stream, 999
    )

    await anext(iterator)
    ready = await anext(iterator)
    assert "id: 2" in ready
    await iterator.aclose()


@pytest.mark.asyncio
async def test_replay_is_capped_at_100_and_http_history_covers_the_rest(seeded) -> None:
    factory, college, _, student, _, _, _, _ = seeded
    async with factory() as session:
        await _insert_notifications(session, user_id=student.id, college_id=college.id, count=105)
    app = _test_app(factory, replay_limit=100)
    stream = await _connected_stream(app, student.id)
    iterator = notifications._stream_events(
        _request(app), _principal(student.id, college.id), stream, 0
    )

    # comment + ready + batch-start + 100 events + batch-complete
    chunks = [await anext(iterator) for _ in range(104)]
    notification_chunks = [chunk for chunk in chunks if "event: notification" in chunk]
    sequence_ids = [
        int(next(line[4:] for line in chunk.splitlines() if line.startswith("id: ")))
        for chunk in notification_chunks
    ]
    completed = chunks[-1]

    assert len(notification_chunks) == 100
    # The stream replays the newest 100 pending events; older history is fetched
    # through the paginated HTTP history API.
    assert sequence_ids == list(range(6, 106))
    assert "id: 105" in completed
    assert _data(completed) == {
        "replay": True,
        "deliveredCount": 100,
        "omittedCount": 5,
        "historySyncRequired": True,
    }
    await iterator.aclose()


@pytest.mark.asyncio
async def test_sse_replay_obeys_the_active_college_scope(seeded) -> None:
    factory, college, other_college, student, _, _, _, _ = seeded
    async with factory() as session:
        await _insert_notifications(session, user_id=student.id, college_id=college.id, count=1)
        hidden_sequence = await next_delivery_sequence(session, student.id)
        session.add(
            Notification(
                user_id=student.id,
                college_id=other_college.id,
                type="SYSTEM",
                title="另一个学院的通知",
                content="must not leak",
                delivery_sequence=hidden_sequence,
            )
        )
        visible_sequence = await next_delivery_sequence(session, student.id)
        session.add(
            Notification(
                user_id=student.id,
                college_id=college.id,
                type="SYSTEM",
                title="当前学院通知",
                content="visible",
                delivery_sequence=visible_sequence,
            )
        )
        await session.commit()

    app = _test_app(factory)
    events, pending, high_water, overflow = await notifications._notification_batch(
        _request(app), _principal(student.id, college.id), 1, limit=100
    )

    assert pending == 1
    assert high_water == 3
    assert overflow is False
    assert len(events) == 1
    assert events[0]["title"] == "当前学院通知"
    assert "另一个学院的通知" not in str(events)


@pytest.mark.asyncio
async def test_live_notification_is_emitted_after_a_user_stream_wake(seeded) -> None:
    """Unit/data-flow: a committed row plus a hub wake produces one SSE event."""
    factory, college, _, student, _, _, _, _ = seeded
    app = _test_app(factory)
    principal = _principal(student.id, college.id)
    stream = await _connected_stream(app, student.id)
    iterator = notifications._stream_events(_request(app), principal, stream, None)

    assert await anext(iterator) == ": connected\n\n"
    assert "event: stream-ready" in await anext(iterator)
    async with factory() as session:
        sequence = await next_delivery_sequence(session, student.id)
        session.add(
            Notification(
                user_id=student.id,
                college_id=college.id,
                type="SYSTEM",
                title="实时通知测试",
                content="由持久化行驱动 SSE 推送",
                delivery_sequence=sequence,
            )
        )
        await session.commit()
    await app.state.notification_hub.publish(
        student.id,
        {
            "eventType": "notification",
            "id": 1,
            "userId": student.id,
            "deliverySequence": sequence,
            "type": "SYSTEM",
            "title": "实时通知测试",
            "content": "由 Stream 消息驱动 SSE 推送",
            "isRead": 0,
            "createdAt": "2026-01-01T00:00:00",
        },
    )

    assert "event: batch-start" in await anext(iterator)
    notification_event = await anext(iterator)
    assert "event: notification" in notification_event
    assert "id: 1" in notification_event
    assert _data(notification_event)["title"] == "实时通知测试"
    await iterator.aclose()


@pytest.mark.asyncio
async def test_live_stream_fills_sequence_gap_from_mysql_before_later_event(seeded) -> None:
    factory, college, _, student, _, _, _, _ = seeded
    async with factory() as session:
        first_sequence = await next_delivery_sequence(session, student.id)
        session.add(
            Notification(
                user_id=student.id,
                college_id=college.id,
                type="SYSTEM",
                title="第一条",
                content="cursor head",
                delivery_sequence=first_sequence,
            )
        )
        await session.commit()

    app = _test_app(factory)
    principal = _principal(student.id, college.id)
    stream = await _connected_stream(app, student.id)
    iterator = notifications._stream_events(_request(app), principal, stream, None)
    assert await anext(iterator) == ": connected\n\n"
    assert "event: stream-ready" in await anext(iterator)

    async with factory() as session:
        second_sequence = await next_delivery_sequence(session, student.id)
        second = Notification(
            user_id=student.id,
            college_id=college.id,
            type="SYSTEM",
            title="第二条",
            content="fill the gap",
            delivery_sequence=second_sequence,
        )
        session.add(second)
        await session.flush()
        second_id = second.id
        third_sequence = await next_delivery_sequence(session, student.id)
        third = Notification(
            user_id=student.id,
            college_id=college.id,
            type="SYSTEM",
            title="第三条",
            content="arrived first through Stream",
            delivery_sequence=third_sequence,
        )
        session.add(third)
        await session.commit()
        third_id = third.id

    await app.state.notification_hub.publish(
        student.id,
        {
            "eventType": "notification",
            "id": third_id,
            "userId": student.id,
            "deliverySequence": third_sequence,
            "title": "第三条",
            "content": "arrived first through Stream",
        },
    )
    assert "event: batch-start" in await anext(iterator)
    second_event = await anext(iterator)
    third_event = await anext(iterator)
    assert "id: 2" in second_event
    assert _data(second_event)["title"] == "第二条"
    assert f"id: {third_sequence}" in third_event
    assert _data(third_event)["id"] == third_id
    assert second_id != third_id
    await iterator.aclose()


@pytest.mark.asyncio
async def test_streamed_http_interface_ignores_foreign_user_and_college_cursor(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interface: a caller cannot select another college's notification owner."""
    factory, college, other_college, student, other_student, _, _, _ = seeded
    async with factory() as session:
        await _insert_notifications(session, user_id=student.id, college_id=college.id, count=1)
        foreign_sequence = await next_delivery_sequence(session, other_student.id)
        session.add(
            Notification(
                user_id=other_student.id,
                college_id=other_college.id,
                type="SYSTEM",
                title="跨学院私有通知",
                content="must not leak",
                delivery_sequence=foreign_sequence,
            )
        )
        await session.commit()

    principal = _principal(student.id, college.id)
    app = _interface_app(factory, principal=principal)

    async def resolve_test_principal(_request):
        return app.state.test_principal

    async def pass_rate_limit(_request, resolved_principal):
        return resolved_principal

    monkeypatch.setattr(
        notifications, "resolve_notification_stream_principal", resolve_test_principal
    )
    monkeypatch.setattr(notifications, "enforce_authenticated_rate_limit", pass_rate_limit)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v2/notifications/stream",
            params={"user_id": other_student.id},
            headers={"Last-Event-ID": "0"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"title":"通知 1"' in response.text
    assert "跨学院私有通知" not in response.text
    assert "auth-revoked" in response.text


@pytest.mark.asyncio
async def test_eventsource_endpoint_authenticates_and_closes_its_registered_stream(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, college, _, student, _, _, _, _ = seeded
    app = _test_app(factory)
    principal = _principal(student.id, college.id)
    monkeypatch.setattr(
        notifications,
        "resolve_notification_stream_principal",
        lambda _request: _async_result(principal),
    )

    response = await notifications.notification_stream(_request(app))
    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    first_chunk = await anext(response.body_iterator)
    assert first_chunk == ": connected\n\n"
    await response.body_iterator.aclose()
    assert not app.state.notification_hub._connections


async def _async_result(value):
    return value


@pytest.mark.asyncio
async def test_revoking_a_session_closes_its_active_sse_stream(seeded) -> None:
    """Unit: logout's session revocation makes the stream emit a terminal event."""
    factory, college, _, student, _, _, _, _ = seeded
    app = _test_app(factory)
    stream = await _connected_stream(app, student.id)
    iterator = notifications._stream_events(
        _request(app), _principal(student.id, college.id), stream, None
    )

    await anext(iterator)
    await anext(iterator)
    waiting_chunk = asyncio.create_task(anext(iterator))
    # Let the generator enter NotificationHub.wait before revoking its session.
    await asyncio.sleep(0)
    await app.state.notification_hub.disconnect_session("session-1")

    assert "event: auth-revoked" in await waiting_chunk
    assert not app.state.notification_hub._connections
    await iterator.aclose()


@pytest.mark.asyncio
async def test_sse_rejects_untrusted_origin_before_reserving_capacity(seeded) -> None:
    factory, _, _, _, _, _, _, _ = seeded
    app = _test_app(factory)

    with pytest.raises(ApiError) as error:
        await notifications.notification_stream(_request(app, origin="https://evil.example"))

    assert error.value.status_code == 403
    assert not app.state.notification_hub._pending


@pytest.mark.asyncio
async def test_stream_auth_uses_the_cookie_and_requires_notification_permission(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, college, _, student, _, _, _, _ = seeded
    app = _test_app(factory)
    request_without_cookie = _request(app)
    with pytest.raises(ApiError) as missing_cookie:
        await notifications.resolve_notification_stream_principal(request_without_cookie)
    assert missing_cookie.value.status_code == 401

    request = _request(app, cookie="lab_access=opaque-token")
    allowed = _principal(student.id, college.id)

    async def resolve_allowed(_request, token, _session):
        assert token == "opaque-token"
        return allowed

    monkeypatch.setattr(notifications, "resolve_principal", resolve_allowed)
    assert await notifications.resolve_notification_stream_principal(request) == allowed

    denied = Principal(
        user_id=student.id,
        username=student.username,
        college_id=college.id,
        roles=(),
        token_type="access",
        token_id="no-notification-permission",
        permissions=(),
        session_id="session-1",
    )

    async def resolve_denied(_request, _token, _session):
        return denied

    monkeypatch.setattr(notifications, "resolve_principal", resolve_denied)
    with pytest.raises(ApiError) as forbidden:
        await notifications.resolve_notification_stream_principal(request)
    assert forbidden.value.status_code == 403


@pytest.mark.asyncio
async def test_long_lived_stream_rechecks_active_user_scope_and_permission(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, college, other_college, student, _, _, _, _ = seeded
    app = _test_app(factory)
    request = _request(app)
    principal = _principal(student.id, college.id)
    expires_at = int(time.time()) + 300

    async def current_session(_request, session_id):
        assert session_id == principal.session_id
        return {"user_id": str(student.id), "expires_at": str(expires_at)}

    monkeypatch.setattr(notifications, "get_session", current_session)
    monkeypatch.setattr(
        notifications,
        "get_authorization_snapshot",
        lambda *_args, **_kwargs: _async_result(
            SimpleNamespace(roles=(), permissions=("notification:read:own",))
        ),
    )
    assert await notifications._stream_still_authorized(request, principal)

    async def denied_snapshot(*_args, **_kwargs):
        return SimpleNamespace(roles=(), permissions=())

    monkeypatch.setattr(notifications, "get_authorization_snapshot", denied_snapshot)
    assert not await notifications._stream_still_authorized(request, principal)

    async with factory() as session:
        user = await session.get(User, student.id)
        assert user is not None
        user.college_id = other_college.id
        await session.commit()
    assert not await notifications._stream_still_authorized(request, principal)


def test_last_event_id_accepts_only_nonnegative_integer_cursors() -> None:
    assert notifications._last_event_cursor(None) is None
    assert notifications._last_event_cursor("0") == 0
    assert notifications._last_event_cursor("123") == 123
    for invalid in ("-1", "1,2", "x" * 20, "9223372036854775808"):
        with pytest.raises(ApiError):
            notifications._last_event_cursor(invalid)


@pytest.mark.asyncio
async def test_mysql_concurrent_notification_creation_preserves_sequence_and_sse_order(
    capsys,
) -> None:
    """Integration: MySQL row locks serialize concurrent per-user allocations."""
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to verify MySQL row-lock semantics")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("SQLite does not verify MySQL SELECT FOR UPDATE semantics")

    prefix = f"e2e-sse-seq-{secrets.token_hex(4)}"
    engine = None
    fixture_created = False
    try:
        await seed(prefix)
        fixture_created = True
        capsys.readouterr()
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            student = await session.scalar(
                select(User).where(User.username == f"{prefix}-user")
            )
            assert student is not None
            user_id = student.id
            college_id = student.college_id

        contender_count = 16
        start_together = asyncio.Barrier(contender_count)

        async def create_notification(contender: int) -> tuple[int, str]:
            async with factory() as session:
                await start_together.wait()
                sequence = await next_delivery_sequence(session, user_id)
                title = f"并发通知 {contender}"
                session.add(
                    Notification(
                        user_id=user_id,
                        college_id=college_id,
                        type="SYSTEM",
                        title=title,
                        content="MySQL concurrent sequence integration",
                        delivery_sequence=sequence,
                    )
                )
                await session.commit()
                return sequence, title

        created = await asyncio.gather(
            *(create_notification(contender) for contender in range(contender_count))
        )
        assert sorted(sequence for sequence, _ in created) == list(
            range(1, contender_count + 1)
        )

        async with factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Notification)
                        .where(Notification.user_id == user_id)
                        .order_by(Notification.delivery_sequence.asc())
                    )
                ).all()
            )
        assert [row.delivery_sequence for row in rows] == list(
            range(1, contender_count + 1)
        )
        assert len({row.id for row in rows}) == contender_count

        app = _test_app(factory)
        events, pending, high_water, overflow = await notifications._notification_batch(
            _request(app), _principal(user_id, college_id), 0, limit=100
        )
        delivered_sequences = [int(event["deliverySequence"]) for event in events]
        assert pending == contender_count
        assert high_water == contender_count
        assert overflow is False
        assert delivered_sequences == list(range(1, contender_count + 1))
    finally:
        if engine is not None:
            await engine.dispose()
        if fixture_created:
            await cleanup(prefix)
