import pytest
from app.infrastructure.notifications.realtime import NotificationHub


@pytest.mark.asyncio
async def test_sse_pending_and_authenticated_connections_are_bounded() -> None:
    hub = NotificationHub()
    pending = await hub.reserve_pending("192.0.2.1", max_pending=2, max_per_ip=1)
    assert pending is not None
    assert await hub.reserve_pending("192.0.2.1", max_pending=2, max_per_ip=1) is None
    assert await hub.connect(1, pending, max_total=1, max_per_user=1, session_id="sid-1")

    other_ip = await hub.reserve_pending("198.51.100.2", max_pending=2, max_per_ip=1)
    assert other_ip is not None
    assert not await hub.connect(2, other_ip, max_total=1, max_per_user=1)
    await hub.disconnect_pending(other_ip)

    same_user = await hub.reserve_pending("203.0.113.3", max_pending=2, max_per_ip=1)
    assert same_user is not None
    assert not await hub.connect(1, same_user, max_total=3, max_per_user=1)
    await hub.disconnect_pending(same_user)

    await hub.disconnect(1, pending)
    assert not hub._connections


@pytest.mark.asyncio
async def test_revoked_session_wakes_only_its_streams() -> None:
    hub = NotificationHub()
    revoked = await hub.reserve_pending("192.0.2.5", max_pending=3, max_per_ip=3)
    other = await hub.reserve_pending("192.0.2.5", max_pending=3, max_per_ip=3)
    assert revoked is not None and other is not None
    assert await hub.connect(9, revoked, max_total=3, max_per_user=3, session_id="revoked")
    assert await hub.connect(9, other, max_total=3, max_per_user=3, session_id="active")

    await hub.disconnect_session("revoked")

    assert revoked.closed.is_set()
    assert revoked.wake.is_set()
    assert not other.closed.is_set()
    assert await hub.take_pending(other) == (False, False)
    assert hub._connections == {9: {other}}


@pytest.mark.asyncio
async def test_hub_coalesces_notification_and_read_state_wakeups_per_user() -> None:
    hub = NotificationHub()
    stream_a = await hub.reserve_pending("192.0.2.1", max_pending=4, max_per_ip=4)
    stream_b = await hub.reserve_pending("192.0.2.2", max_pending=4, max_per_ip=4)
    stream_other_user = await hub.reserve_pending("192.0.2.3", max_pending=4, max_per_ip=4)
    assert stream_a is not None and stream_b is not None and stream_other_user is not None
    assert await hub.connect(5, stream_a, max_total=4, max_per_user=3)
    assert await hub.connect(5, stream_b, max_total=4, max_per_user=3)
    assert await hub.connect(6, stream_other_user, max_total=4, max_per_user=3)

    assert await hub.publish(5, {"eventType": "notification", "id": 81}) == 2
    assert await hub.publish(5, {"eventType": "read_state_changed", "all": True}) == 2
    assert await hub.take_pending(stream_a) == (True, True)
    assert await hub.take_pending(stream_b) == (True, True)
    assert await hub.take_pending(stream_other_user) == (False, False)


@pytest.mark.asyncio
async def test_hub_deduplicates_notification_ids_and_signals_queue_overflow() -> None:
    hub = NotificationHub(max_pending_events=2)
    stream = await hub.reserve_pending("192.0.2.9", max_pending=1, max_per_ip=1)
    assert stream is not None
    assert await hub.connect(5, stream, max_total=1, max_per_user=1)

    await hub.publish(
        5,
        {"eventType": "notification", "id": 10, "deliverySequence": 1},
    )
    await hub.publish(
        5,
        {"eventType": "notification", "id": 10, "deliverySequence": 2},
    )
    await hub.publish(
        5,
        {"eventType": "notification", "id": 11, "deliverySequence": 2},
    )
    await hub.publish(
        5,
        {"eventType": "notification", "id": 12, "deliverySequence": 3},
    )

    events, read_state, overflow_sequence, fallback = await hub.take_events(stream)
    assert events == []
    assert read_state is False
    assert overflow_sequence == 3
    assert fallback is False


@pytest.mark.asyncio
async def test_pending_stream_overflow_is_rejected() -> None:
    hub = NotificationHub()
    first = await hub.reserve_pending("192.0.2.1", max_pending=1, max_per_ip=2)
    assert first is not None
    assert await hub.reserve_pending("192.0.2.2", max_pending=1, max_per_ip=2) is None
    await hub.disconnect_pending(first)
