import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.db.models import Notification, OutboxTask
from app.infrastructure.db.session import get_db
from app.infrastructure.notifications.sequence import next_delivery_sequence
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select


@pytest.mark.asyncio
async def test_notifications_use_camel_case_unread_filter_and_update_count(seeded) -> None:
    factory, college, _, student1, _, _, _, _ = seeded
    async with factory() as session:
        unread_sequence = await next_delivery_sequence(session, student1.id)
        unread = Notification(
            user_id=student1.id,
            college_id=college.id,
            type="SYSTEM",
            title="未读通知",
            content="请查看",
            is_read=False,
            delivery_sequence=unread_sequence,
        )
        session.add(unread)
        read_sequence = await next_delivery_sequence(session, student1.id)
        read = Notification(
            user_id=student1.id,
            college_id=college.id,
            type="SYSTEM",
            title="已读通知",
            content="已查看",
            is_read=True,
            delivery_sequence=read_sequence,
        )
        session.add_all([unread, read])
        await session.commit()
        unread_id = unread.id

    app = create_app(
        Settings(
            environment="test",
            cors_origins=[],
            enable_workers=False,
            rate_limit_enabled=False,
        )
    )

    async def override_db():
        async with factory() as session:
            yield session

    actor = {
        "principal": Principal(
            user_id=student1.id,
            username=student1.username,
            college_id=college.id,
            roles=(),
            token_type="access",
            token_id="notification-test",
            permissions=("notification:read:own",),
        )
    }

    async def override_principal() -> Principal:
        return actor["principal"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal
    app.dependency_overrides[enforce_csrf] = lambda: None
    stream = await app.state.notification_hub.reserve_pending(
        "192.0.2.10", max_pending=2, max_per_ip=2
    )
    assert stream is not None
    assert await app.state.notification_hub.connect(
        student1.id,
        stream,
        max_total=2,
        max_per_user=2,
        session_id="notification-test-session",
    )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            unread_page = await client.get(
                "/api/v2/notifications/mine",
                params={"onlyUnread": "true", "page": 1, "size": 10},
            )
            assert unread_page.status_code == 200
            assert unread_page.json()["data"]["total"] == 1
            assert unread_page.json()["data"]["records"][0]["id"] == unread_id

            actor["principal"] = Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=college.id,
                roles=(),
                token_type="access",
                token_id="notification-no-permission",
            )
            denied = await client.patch(f"/api/v2/notifications/{unread_id}/read")
            assert denied.status_code == 403
            actor["principal"] = Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=college.id,
                roles=(),
                token_type="access",
                token_id="notification-test",
                permissions=("notification:read:own",),
            )

            marked = await client.patch(f"/api/v2/notifications/{unread_id}/read")
            assert marked.status_code == 200
            assert await app.state.notification_hub.take_pending(stream) == (False, False)
            async with factory() as session:
                read_state_task = await session.scalar(
                    select(OutboxTask).where(
                        OutboxTask.task_type == "NOTIFICATION_READ_STATE",
                        OutboxTask.payload["notification_id"].as_integer() == unread_id,
                    )
                )
                assert read_state_task is not None
            missing = await client.patch("/api/v2/notifications/999999/read")
            assert missing.status_code == 404

            async with factory() as session:
                next_sequence = await next_delivery_sequence(session, student1.id)
                session.add(
                    Notification(
                        user_id=student1.id,
                        college_id=college.id,
                        type="SYSTEM",
                        title="批量已读测试",
                        content="批量更新也要生成 Outbox 事件",
                        is_read=False,
                        delivery_sequence=next_sequence,
                    )
                )
                await session.commit()
            mark_all = await client.patch("/api/v2/notifications/read-all")
            assert mark_all.status_code == 200
            async with factory() as session:
                read_state_tasks = list(
                    (
                        await session.scalars(
                            select(OutboxTask).where(
                                OutboxTask.task_type == "NOTIFICATION_READ_STATE"
                            )
                        )
                    ).all()
                )
                assert len(read_state_tasks) == 2
                assert any(task.payload.get("all") is True for task in read_state_tasks)

            actor["principal"] = Principal(
                user_id=student1.id,
                username=student1.username,
                college_id=None,
                roles=("SYS_ADMIN",),
                token_type="access",
                token_id="notification-global-scope",
                permissions=("notification:read:own",),
            )
            global_scope = await client.get("/api/v2/notifications/mine")
            assert global_scope.status_code == 200
            assert global_scope.json()["data"]["total"] == 3

            empty_unread_page = await client.get(
                "/api/v2/notifications/mine",
                params={"onlyUnread": "true", "page": 1, "size": 10},
            )
            assert empty_unread_page.status_code == 200
            assert empty_unread_page.json()["data"]["total"] == 0
            assert empty_unread_page.json()["data"]["records"] == []
    finally:
        app.dependency_overrides.clear()
