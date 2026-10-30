"""ORM models for holder sessions, email OTPs, and password resets."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class HolderSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One signed-in device of a holder.

    Access tokens carry the session id, and every authenticated request
    checks that the session has neither ended nor expired. Ending the
    session therefore revokes its token at once.
    """

    __tablename__ = "holder_sessions"

    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class EmailOtp(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A one-time code emailed to prove control of an address.

    Only the HMAC of the code is stored. A code is usable once, until
    ``expires_at``, and for at most ``OTP_MAX_ATTEMPTS`` wrong guesses.
    ``consumed_at`` records the successful verification; ``used_at``
    records the registration that relied on it, so one verification
    creates at most one account.

    A successful verification also issues a login token, stored as
    ``login_token_hash``, that signs the new account in once after
    registration; ``signed_in_at`` records that use.
    """

    __tablename__ = "email_otps"

    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    login_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )
    signed_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class PasswordResetToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single-use password reset token; only its HMAC is stored."""

    __tablename__ = "password_reset_tokens"

    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
