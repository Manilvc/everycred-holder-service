"""ORM model for the holder audit trail."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class AuditAction(StrEnum):
    """Security-relevant holder actions recorded in the audit trail."""

    REGISTERED = "registered"
    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGGED_OUT = "logged_out"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105 - not a secret
    PASSWORD_RESET = "password_reset"  # noqa: S105 - not a secret
    PROFILE_UPDATED = "profile_updated"
    KEY_REGISTERED = "key_registered"
    KEY_REVOKED = "key_revoked"
    CREDENTIAL_SHARED = "credential_shared"
    CREDENTIAL_DOWNLOADED = "credential_downloaded"
    CREDENTIAL_EMAILED = "credential_emailed"
    PRESENTATION_STORED = "presentation_stored"


class HolderAuditLog(UUIDPrimaryKeyMixin, Base):
    """One recorded action. Holds ids only, never personal data."""

    __tablename__ = "holder_audit_logs"
    __table_args__ = (
        Index(
            "ix_holder_audit_logs_holder_action_created",
            "holder_id",
            "action",
            "created_at",
        ),
    )

    holder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holders.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utc_now, nullable=False
    )
