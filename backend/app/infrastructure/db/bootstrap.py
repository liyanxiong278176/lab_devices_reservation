from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import hash_password
from app.core.settings import Settings
from app.infrastructure.db.models import Role, User


async def ensure_bootstrap_admin(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Create the first global admin only when an operator supplies a password.

    No password is shipped in code or compose defaults. Existing accounts are
    never overwritten, which makes repeated startup and multiple app workers
    safe. A unique username constraint handles a startup race between workers.
    """

    if not settings.bootstrap_admin_password:
        return
    async with session_factory() as session:
        existing = await session.scalar(
            select(User).where(User.username == settings.bootstrap_admin_username)
        )
        if existing is not None:
            return
        role = await session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
        if role is None:
            return
        session.add(
            User(
                username=settings.bootstrap_admin_username,
                password_hash=hash_password(settings.bootstrap_admin_password),
                real_name="系统管理员",
                user_type="STAFF",
                college_id=None,
                status=1,
                roles=[role],
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # Another worker created the same account first.
            await session.rollback()
