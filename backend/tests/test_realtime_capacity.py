import pytest
from app.infrastructure.notifications.realtime import NotificationHub


@pytest.mark.asyncio
async def test_websocket_pending_and_authenticated_connections_are_bounded() -> None:
    hub = NotificationHub()
    pending = object()
    same_ip_pending = object()
    another_user = object()

    assert await hub.reserve_pending(pending, "192.0.2.1", max_pending=2, max_per_ip=1)
    assert not await hub.reserve_pending(
        same_ip_pending,
        "192.0.2.1",
        max_pending=2,
        max_per_ip=1,
    )
    assert await hub.connect(pending_user := 1, pending, max_total=1, max_per_user=1)

    assert await hub.reserve_pending(another_user, "198.51.100.2", max_pending=2, max_per_ip=1)
    assert not await hub.connect(2, another_user, max_total=1, max_per_user=1)
    await hub.disconnect_pending(another_user)

    third = object()
    assert await hub.reserve_pending(third, "203.0.113.3", max_pending=2, max_per_ip=1)
    assert not await hub.connect(pending_user, third, max_total=3, max_per_user=1)
    await hub.disconnect_pending(third)

    await hub.disconnect(pending_user, pending)
    assert hub._connections == {}


@pytest.mark.asyncio
async def test_revoked_session_disconnects_only_its_live_sockets() -> None:
    class Socket:
        closed_with: int | None = None

        async def close(self, *, code: int) -> None:
            self.closed_with = code

    hub = NotificationHub()
    revoked_socket = Socket()
    other_socket = Socket()
    sessions = ((revoked_socket, "revoked-family"), (other_socket, "other-family"))
    for websocket, session_id in sessions:
        assert await hub.reserve_pending(websocket, "192.0.2.5", max_pending=3, max_per_ip=3)
        assert await hub.connect(
            9,
            websocket,
            max_total=3,
            max_per_user=3,
            session_id=session_id,
        )

    await hub.disconnect_session("revoked-family")

    assert revoked_socket.closed_with == 4401
    assert other_socket.closed_with is None
    assert hub._connections == {9: {other_socket}}
