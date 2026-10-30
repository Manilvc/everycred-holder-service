"""Column types and mixins shared by ORM models.

MySQL ``DATETIME`` columns store no time zone, and drivers hand back
naive datetimes. :class:`UTCDateTime` stores every value as naive UTC
and returns it as an aware UTC datetime, so application code can always
compare against ``datetime.now(UTC)`` without ``TypeError``.
"""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

# Public numeric ids stay below 2**53 so JavaScript clients (the wallet
# app) can hold them in a number without losing precision.
_PUBLIC_ID_UPPER_BOUND = 2**52


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def to_naive_iso(value: datetime | None) -> str | None:
    """Format a datetime the way the DCS does: naive UTC ISO-8601."""
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None).isoformat()


def generate_public_id() -> int:
    """Return a random positive integer id that is safe in JavaScript.

    The wallet app identifies holders and credentials by integer ids.
    Random values (rather than a sequence) do not reveal how many rows
    exist and cannot be guessed by counting.
    """
    return secrets.randbelow(_PUBLIC_ID_UPPER_BOUND - 1) + 1


class UTCDateTime(TypeDecorator[datetime]):
    """Datetime column that is always UTC on the way in and out."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Convert an aware datetime to naive UTC before saving."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires timezone-aware datetimes")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Mark a naive value loaded from the database as UTC."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class UUIDPrimaryKeyMixin:
    """Adds a random UUID primary key named ``id``.

    Random ids do not reveal how many records exist and can be created
    before the row is inserted.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns set automatically."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utc_now, onupdate=utc_now, nullable=False
    )
