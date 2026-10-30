"""ORM model mapping the wallet's integer credential ids to sources.

The wallet app refers to a credential by an integer ``id`` (DCS
``credential.id``), for example as ``cred_id`` when sharing it. The
holder service stores no credentials, and several DCS sources could
use the same integer, so each (source, credential) pair a holder sees
is given a random integer of its own here. Only these references are
stored, never credential contents.
"""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import (
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    generate_public_id,
)


class CredentialRef(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A holder's integer handle for one credential at one source."""

    __tablename__ = "credential_refs"
    __table_args__ = (
        UniqueConstraint("holder_id", "source_code", "credential_id"),
    )

    numeric_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, default=generate_public_id
    )
    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE"), index=True
    )
    source_code: Mapped[str] = mapped_column(String(64))
    credential_id: Mapped[str] = mapped_column(String(128))
