"""ORM model for wallet push notification tokens."""

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class DevicePlatform(StrEnum):
    """Platforms the wallet runs on."""

    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class PushToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An FCM registration token of one wallet install.

    The token is bound to the session that registered it, so ending the
    session (logout, password change) also stops pushes to that device.
    A token is unique: when another holder signs in on the same device,
    the row moves to them instead of both receiving pushes.
    """

    __tablename__ = "push_tokens"

    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holder_sessions.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(512), unique=True)
    platform: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
