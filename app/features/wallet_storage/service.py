"""Temporary storage of verifiable presentations the wallet shares.

The wallet builds a presentation on the device, uploads it here, and
puts the returned URL in a QR code. The URL works for the window the
wallet asks for (``valid_from`` to ``valid_until``), as in the DCS.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import PayloadTooLargeError
from app.core.models import utc_now
from app.core.storage import ObjectStorage
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.holders.models import Holder
from app.features.wallet_storage.exceptions import InvalidPresentationError
from app.features.wallet_storage.schemas import HolderStorageRequest

_DCS_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _as_utc(value: datetime) -> datetime:
    # A datetime without a zone is taken as UTC, as the DCS does.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class PresentationStorageService:
    """Stores presentations for one holder.

    Attributes:
        session: Unit of work; used for the audit entry.
        storage: Where presentations are written.
        settings: Size limit and sharing window bounds.
    """

    def __init__(
        self,
        session: AsyncSession,
        storage: ObjectStorage,
        settings: Settings,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.audit = AuditRepository(session)

    async def store_presentation(
        self, holder: Holder, payload: HolderStorageRequest
    ) -> dict[str, Any]:
        """Store the presentation and return its URL and window.

        Raises:
            PayloadTooLargeError: The presentation is too large.
            InvalidPresentationError: The window ends before it starts
                or is longer than ``PRESENTATION_MAX_WINDOW_SECONDS``.
        """
        content = json.dumps(payload.data, separators=(",", ":")).encode()
        if len(content) > self.settings.max_presentation_bytes:
            raise PayloadTooLargeError(
                "The presentation must not be larger than "
                f"{self.settings.max_presentation_bytes} bytes."
            )
        valid_from, valid_until = self._window(payload)
        presentation_id = uuid.uuid4()
        key = f"holders/{holder.id}/presentations/{presentation_id}.json"
        await self.storage.put(key, content, "application/json")
        lifetime = int((valid_until - utc_now()).total_seconds())
        file_url = await self.storage.url_for(
            key, ttl_seconds=max(lifetime, 1)
        )
        self.audit.record(
            holder.id,
            AuditAction.PRESENTATION_STORED,
            resource_type="presentation",
            resource_id=str(presentation_id),
        )
        await self.session.commit()
        return {
            "file_path": file_url,
            "valid_from": valid_from.strftime(_DCS_TIME_FORMAT),
            "valid_until": valid_until.strftime(_DCS_TIME_FORMAT),
        }

    def _window(
        self, payload: HolderStorageRequest
    ) -> tuple[datetime, datetime]:
        # The DCS crashed when only one date was sent; here the missing
        # end is filled in with the default window instead.
        default = timedelta(
            seconds=self.settings.presentation_default_window_seconds
        )
        valid_from = (
            _as_utc(payload.valid_from) if payload.valid_from else utc_now()
        )
        valid_until = (
            _as_utc(payload.valid_until)
            if payload.valid_until
            else valid_from + default
        )
        if valid_until <= valid_from or valid_until <= utc_now():
            raise InvalidPresentationError(
                "valid_until must be after valid_from and in the future."
            )
        maximum = timedelta(
            seconds=self.settings.presentation_max_window_seconds
        )
        if valid_until - utc_now() > maximum:
            raise InvalidPresentationError(
                "The sharing window must not be longer than "
                f"{self.settings.presentation_max_window_seconds} seconds."
            )
        return valid_from, valid_until
