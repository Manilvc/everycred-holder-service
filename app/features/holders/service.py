"""Reading and updating the signed-in holder's profile."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import ObjectStorage
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.holders.exceptions import UnsupportedImageError
from app.features.holders.models import Holder
from app.features.holders.schemas import (
    HolderProfileResponse,
    HolderProfileUpdate,
)
from app.shared.uploads import detect_image_type

_IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


class HolderProfileService:
    """Profile reads and edits for one holder.

    Attributes:
        session: Unit of work; the service commits its own changes.
        storage: Where profile images are stored.
    """

    def __init__(self, session: AsyncSession, storage: ObjectStorage) -> None:
        self.session = session
        self.storage = storage
        self.audit = AuditRepository(session)

    async def get_profile(self, holder: Holder) -> HolderProfileResponse:
        """Return the profile with fresh URLs for the holder's files."""
        image_url, qr_url, profile_url = await asyncio.gather(
            self._url_or_none(holder.profile_image_key),
            self._url_or_none(holder.qr_code_key),
            self._url_or_none(holder.profile_document_key),
        )
        return HolderProfileResponse(
            id=holder.id,
            email=holder.email,
            did=holder.did,
            full_name=holder.full_name,
            mobile=holder.mobile,
            profile_image_url=image_url,
            did_qr_code_url=qr_url,
            did_profile_url=profile_url,
            created_at=holder.created_at,
        )

    async def update_profile(
        self, holder: Holder, changes: HolderProfileUpdate
    ) -> HolderProfileResponse:
        """Apply the fields present in ``changes``."""
        for field_name, field_value in changes.model_dump(
            exclude_unset=True
        ).items():
            setattr(holder, field_name, field_value)
        self.audit.record(holder.id, AuditAction.PROFILE_UPDATED)
        await self.session.commit()
        return await self.get_profile(holder)

    async def replace_profile_image(
        self, holder: Holder, content: bytes
    ) -> HolderProfileResponse:
        """Store a new profile image after checking its file type.

        Raises:
            UnsupportedImageError: The bytes are not PNG, JPEG, or WebP.
        """
        media_type = detect_image_type(content)
        if media_type is None:
            raise UnsupportedImageError(
                "The profile image must be PNG, JPEG, or WebP."
            )
        key = (
            f"holders/{holder.id}/profile-image."
            f"{_IMAGE_EXTENSIONS[media_type]}"
        )
        await self.storage.put(key, content, media_type)
        holder.profile_image_key = key
        self.audit.record(holder.id, AuditAction.PROFILE_UPDATED)
        await self.session.commit()
        return await self.get_profile(holder)

    async def _url_or_none(self, key: str | None) -> str | None:
        return await self.storage.url_for(key) if key else None
