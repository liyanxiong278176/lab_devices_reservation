import pytest
from app.auth.security import verify_password
from app.core.settings import Settings
from app.infrastructure.db.bootstrap import ensure_bootstrap_admin
from app.infrastructure.db.models import Role, User
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_bootstrap_admin_is_opt_in_and_idempotent(session_factory) -> None:
    async with session_factory() as session:
        session.add(Role(role_code="SYS_ADMIN", role_name="系统管理员"))
        await session.commit()

    settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        bootstrap_admin_password="strong-admin-password",
    )
    await ensure_bootstrap_admin(session_factory, settings)
    await ensure_bootstrap_admin(session_factory, settings)

    async with session_factory() as session:
        admin = await session.scalar(select(User).where(User.username == "admin"))
        count = int(
            await session.scalar(select(func.count(User.id)).where(User.username == "admin")) or 0
        )

    assert admin is not None
    assert count == 1
    assert verify_password("strong-admin-password", admin.password_hash)
