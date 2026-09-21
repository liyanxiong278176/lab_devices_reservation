import pytest
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.db.models import Notification
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_notifications_use_camel_case_unread_filter_and_update_count(seeded) -> None:
    factory, college, _, student1, _, _, _, _ = seeded
    async with factory() as session:
        unread = Notification(
            user_id=student1.id,
            college_id=college.id,
            type="SYSTEM",
            title="未读通知",
            content="请查看",
            is_read=False,
        )
        read = Notification(
            user_id=student1.id,
            college_id=college.id,
            type="SYSTEM",
            title="已读通知",
            content="已查看",
            is_read=True,
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

    async def override_principal() -> Principal:
        return Principal(
            user_id=student1.id,
            username=student1.username,
            college_id=college.id,
            roles=(),
            token_type="access",
            token_id="notification-test",
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            unread_page = await client.get(
                "/api/v2/notifications/mine",
                params={"onlyUnread": "true", "page": 1, "size": 10},
            )
            assert unread_page.status_code == 200
            assert unread_page.json()["data"]["total"] == 1
            assert unread_page.json()["data"]["records"][0]["id"] == unread_id

            marked = await client.patch(f"/api/v2/notifications/{unread_id}/read")
            assert marked.status_code == 200

            empty_unread_page = await client.get(
                "/api/v2/notifications/mine",
                params={"onlyUnread": "true", "page": 1, "size": 10},
            )
            assert empty_unread_page.status_code == 200
            assert empty_unread_page.json()["data"]["total"] == 0
            assert empty_unread_page.json()["data"]["records"] == []
    finally:
        app.dependency_overrides.clear()
