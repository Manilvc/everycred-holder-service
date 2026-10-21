"""Temporary storage of verifiable presentations the wallet shares.

The wallet builds and signs a presentation on the device, uploads it
here, and shares the returned short-lived URL (for example as a QR
code). The file is stored under the holder's own prefix.
"""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.storage import ObjectStorage
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.holders.models import Holder
from app.features.wallet_storage.exceptions import InvalidPresentationError
from app.features.wallet_storage.schemas import StoredPresentationResponse


class PresentationStorageService:
    """Stores presentations for one holder.

    Attributes:
        session: Unit of work; used for the audit entry.
        storage: Where presentations are written.
        settings: URL lifetime reported to the wallet.
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
        self, holder: Holder, content: bytes
    ) -> StoredPresentationResponse:
        """Validate and store a presentation, returning its URL.

        Raises:
            InvalidPresentationError: The content is not a UTF-8 JSON
                object.
        """
        try:
            document = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidPresentationError(
                "The presentation must be a JSON document."
            ) from exc
        if not isinstance(document, dict):
            raise InvalidPresentationError(
                "The presentation must be a JSON object."
            )
        presentation_id = uuid.uuid4()
        key = f"holders/{holder.id}/presentations/{presentation_id}.json"
        await self.storage.put(key, content, "application/json")
        self.audit.record(
            holder.id,
            AuditAction.PRESENTATION_STORED,
            resource_type="presentation",
            resource_id=str(presentation_id),
        )
        await self.session.commit()
        return StoredPresentationResponse(
            presentation_id=presentation_id,
            url=await self.storage.url_for(key),
            url_expires_in_seconds=self.settings.storage_url_ttl_seconds,
        )
