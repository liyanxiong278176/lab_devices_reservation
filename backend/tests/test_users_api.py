import pytest
from app.api.v2.users import UserRequest, create_user, update_user
from app.auth.security import Principal
from sqlalchemy.ext.asyncio import async_sessionmaker


def system_principal() -> Principal:
    return Principal(
        user_id=999,
        username="admin",
        college_id=None,
        roles=("SYS_ADMIN",),
        token_type="access",
        token_id="test-admin",
    )


@pytest.mark.asyncio
async def test_user_create_and_update_return_loaded_data(seeded) -> None:
    factory, college, _, _, _, _, _, _ = seeded
    engine = factory.kw["bind"]
    expiring_factory = async_sessionmaker(engine, expire_on_commit=True, autoflush=False)

    async with expiring_factory() as session:
        created = await create_user(
            UserRequest(
                username="api-user-response",
                password="123456",
                real_name="接口用户",
                user_type="STUDENT",
                role_codes=["STUDENT"],
                college_id=college.id,
            ),
            system_principal(),
            session,
        )
        assert created.data is not None
        assert created.data["username"] == "api-user-response"
        assert created.data["created_at"] is not None

        updated = await update_user(
            int(created.data["id"]),
            UserRequest(
                username="api-user-response",
                password=None,
                real_name="接口用户已更新",
                user_type="STUDENT",
                role_codes=["STUDENT"],
                college_id=college.id,
            ),
            None,
            system_principal(),
            session,
        )

    assert updated.data is not None
    assert updated.data["real_name"] == "接口用户已更新"
    assert updated.data["created_at"] is not None
