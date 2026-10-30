"""ORM models for invites awaiting sign-up and registration reports."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

REGISTERED_OPERATION = "holder.registered"
PROFILE_UPDATED_OPERATION = "holder.profile_updated"


class ReportStatus(StrEnum):
    """Lifecycle of one registration report."""

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class PendingInvite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An issuer invite for an email that has no account yet.

    The email is stored only as a keyed hash (``email_key``), the same
    way OTP codes are, so the table never holds an address in clear
    text. Rows are turned into inbox notifications and deleted when the
    email registers.
    """

    __tablename__ = "pending_invites"

    email_key: Mapped[str] = mapped_column(String(64), index=True)
    source_code: Mapped[str] = mapped_column(String(64))
    inviter_name: Mapped[str | None] = mapped_column(String(200))


class RegistrationReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Outbox row: tell DCS sources about the holder's account.

    The worker sends it as the connector operation in ``operation``:
    ``holder.registered`` (the holder has an account) or
    ``holder.profile_updated`` (the holder's current name and contact
    number, read when the row is sent). ``source_code`` names one
    source (an invite that arrived after sign-up); None sends it to
    every source the holder is linked to.
    """

    __tablename__ = "registration_reports"
    __table_args__ = (
        Index(
            "ix_registration_reports_status_next_attempt",
            "status",
            "next_attempt_at",
        ),
    )

    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE")
    )
    source_code: Mapped[str | None] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(
        String(40),
        default=REGISTERED_OPERATION,
        server_default=REGISTERED_OPERATION,
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ReportStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(255))
