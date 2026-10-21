"""ORM models for the holder inbox, received events, and the outbox."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class DeliveryChannel(StrEnum):
    """Ways a notification reaches the wallet besides the inbox."""

    SOCKET = "socket"
    PUSH = "push"


class DeliveryStatus(StrEnum):
    """Lifecycle of one outbox row."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    # The channel is not configured, or the holder has no device for it.
    SKIPPED = "skipped"


class InboxNotification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A notification shown in the wallet's inbox.

    The fields mirror the DCS holder inbox payload, so the wallet app
    renders and routes them the same way it does today.
    """

    __tablename__ = "inbox_notifications"
    __table_args__ = (
        Index(
            "ix_inbox_notifications_holder_created", "holder_id", "created_at"
        ),
    )

    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE")
    )
    notification_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(String(1000))
    redirect_module: Mapped[str | None] = mapped_column(String(64))
    redirect_path: Mapped[str | None] = mapped_column(String(512))
    redirect_entity_type: Mapped[str | None] = mapped_column(String(64))
    redirect_entity_id: Mapped[str | None] = mapped_column(String(255))
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


class ConnectorEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A webhook delivery received from the connector.

    Kept so a retried delivery (same ``X-EveryCRED-Delivery`` id) is
    acknowledged without notifying the holder twice. Only ids are
    stored, never the holder's email.
    """

    __tablename__ = "connector_events"

    delivery_id: Mapped[str] = mapped_column(String(128), unique=True)
    event: Mapped[str] = mapped_column(String(64))
    source_code: Mapped[str] = mapped_column(String(64))
    holder_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="SET NULL")
    )


class NotificationDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Outbox row: one notification to send on one channel.

    The background worker sends pending rows whose ``next_attempt_at``
    has passed, retrying failures with backoff.
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index(
            "ix_notification_deliveries_status_next_attempt",
            "status",
            "next_attempt_at",
        ),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inbox_notifications.id", ondelete="CASCADE")
    )
    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(
        String(16), default=DeliveryStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(255))
