"""ORM model for holder accounts."""

from datetime import datetime

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class Holder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A wallet user who holds verifiable credentials.

    The email is the link to DCS sources: credentials and requests are
    matched to a holder by it, so it is stored lower-cased and unique.
    Files (profile image, DID QR code, DID profile document) are stored
    in object storage; only their keys are kept here.
    """

    __tablename__ = "holders"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    did: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(150))
    mobile: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    profile_image_key: Mapped[str | None] = mapped_column(String(512))
    qr_code_key: Mapped[str | None] = mapped_column(String(512))
    profile_document_key: Mapped[str | None] = mapped_column(String(512))
