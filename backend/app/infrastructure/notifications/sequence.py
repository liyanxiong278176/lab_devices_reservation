from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Notification, User


async def next_delivery_sequence(session: AsyncSession, user_id: int) -> int:
    """Reserve the next user-local sequence while holding the user row lock.

    The lock is held until the caller commits the notification row. Concurrent
    Outbox workers for one user therefore cannot commit sequence N+1 before N.
    """
    locked_user_id = await session.scalar(
        select(User.id).where(User.id == user_id).with_for_update()
    )
    if locked_user_id is None:
        raise ValueError(f"notification recipient {user_id} does not exist")
    # Use a locking/current read here. A worker may already have established a
    # repeatable-read snapshot while checking the Outbox idempotency key before
    # it waited on the user row lock; a plain MAX() could then see stale data.
    current = await session.scalar(
        select(Notification.delivery_sequence)
        .where(Notification.user_id == user_id)
        .order_by(Notification.delivery_sequence.desc())
        .limit(1)
        .with_for_update()
    )
    pending = [
        int(item.delivery_sequence)
        for item in session.new
        if isinstance(item, Notification)
        and item.user_id == user_id
        and item.delivery_sequence is not None
    ]
    return max([int(current or 0), *pending]) + 1
