"""Database access for the inbox, received events, and the outbox."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.notifications.models import (
    ConnectorEvent,
    DeliveryStatus,
    InboxNotification,
    NotificationDelivery,
)


class NotificationRepository:
    """Queries and persistence for the notifications feature."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(
        self,
        row: InboxNotification | ConnectorEvent | NotificationDelivery,
    ) -> None:
        """Stage a new row for insertion."""
        self.session.add(row)

    async def has_event(self, delivery_id: str) -> bool:
        """Return True if a delivery with this id was already received."""
        found = await self.session.scalar(
            select(ConnectorEvent.id).where(
                ConnectorEvent.delivery_id == delivery_id
            )
        )
        return found is not None

    async def list_inbox(
        self,
        holder_id: uuid.UUID,
        *,
        unread_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[InboxNotification], int]:
        """Return one page of a holder's inbox, newest first, and total."""
        conditions = [InboxNotification.holder_id == holder_id]
        if unread_only:
            conditions.append(InboxNotification.is_read.is_(False))
        total = await self.session.scalar(
            select(func.count())
            .select_from(InboxNotification)
            .where(*conditions)
        )
        rows = await self.session.scalars(
            select(InboxNotification)
            .where(*conditions)
            .order_by(InboxNotification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return rows.all(), total or 0

    async def get_for_holder(
        self, holder_id: uuid.UUID, notification_id: uuid.UUID
    ) -> InboxNotification | None:
        """Return one of the holder's notifications, if it exists."""
        return await self.session.scalar(
            select(InboxNotification).where(
                InboxNotification.id == notification_id,
                InboxNotification.holder_id == holder_id,
            )
        )

    async def mark_all_read(self, holder_id: uuid.UUID) -> None:
        """Mark every unread notification of the holder as read."""
        await self.session.execute(
            update(InboxNotification)
            .where(
                InboxNotification.holder_id == holder_id,
                InboxNotification.is_read.is_(False),
            )
            .values(is_read=True)
        )

    async def list_due_deliveries(
        self, now: datetime, limit: int
    ) -> Sequence[tuple[NotificationDelivery, InboxNotification]]:
        """Return pending outbox rows that are due, with their notification."""
        rows = await self.session.execute(
            select(NotificationDelivery, InboxNotification)
            .join(
                InboxNotification,
                InboxNotification.id == NotificationDelivery.notification_id,
            )
            .where(
                NotificationDelivery.status == DeliveryStatus.PENDING.value,
                NotificationDelivery.next_attempt_at <= now,
            )
            .order_by(NotificationDelivery.next_attempt_at)
            .limit(limit)
        )
        return [(delivery, notification) for delivery, notification in rows]
