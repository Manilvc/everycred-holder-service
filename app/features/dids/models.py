"""ORM model for holder public keys."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class HolderKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A public key the wallet generated on the device.

    Private keys never leave the device; only the public JWK is stored.
    Active keys are published as verification methods in the holder's
    DID document. Revoked keys are kept so audit entries still resolve.
    """

    __tablename__ = "holder_keys"
    __table_args__ = (UniqueConstraint("holder_id", "key_id"),)

    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE"), index=True
    )
    # Fragment of the verification method id: "<did>#<key_id>".
    key_id: Mapped[str] = mapped_column(String(64))
    algorithm: Mapped[str] = mapped_column(String(16))
    public_jwk: Mapped[dict[str, Any]] = mapped_column(JSON)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
