"""Reading and updating the signed-in holder's profile.

Profiles are returned in the shape of the DCS ``GET /v1/holder``
response, which the wallet app stores as its user profile. Two fields
matter most to the app: ``id`` (the integer it later sends back as
``holder_id``) and ``profile_image`` (an absolute URL or null).
"""

import base64
import binascii
import json
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.models import to_naive_iso, utc_now
from app.core.storage import ObjectStorage
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.dids.service import DID_CONTEXTS
from app.features.holders.exceptions import UnsupportedImageError
from app.features.holders.models import Holder
from app.features.holders.schemas import UpdateHolder
from app.features.onboarding.service import OnboardingService
from app.shared.uploads import detect_image_type

_IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

# The DCS has no other values for accounts created through the wallet.
LOGIN_TYPE_REGISTER = "register"
STATUS_REGISTERED = "registered"

ContactKey = Literal["contact", "phone_number"]


class HolderProfileService:
    """Profile reads and edits for one holder.

    Attributes:
        session: Unit of work; the service commits its own changes.
        storage: Where profile images and documents are stored.
        settings: Profile image size limit.
        onboarding: Queues profile reports to the holder's DCS sources.
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
        self.onboarding = OnboardingService(session, settings)

    async def build_detail(
        self, holder: Holder, contact_key: ContactKey = "contact"
    ) -> dict[str, Any]:
        """Return the holder in the DCS profile shape.

        Args:
            holder: Holder to describe.
            contact_key: ``contact`` for ``GET /v1/holder``;
                ``phone_number`` for the password change and profile
                update responses, which the DCS returns unrenamed.
        """
        profile_image = (
            await self.storage.url_for(holder.profile_image_key)
            if holder.profile_image_key
            else None
        )
        return {
            "id": holder.numeric_id,
            "uuid": str(holder.id),
            "digi_client_id": None,
            "name": holder.full_name,
            "email": holder.email,
            "profile_image": profile_image,
            "login_type": LOGIN_TYPE_REGISTER,
            "did": holder.did,
            "qrcode_path": holder.qr_code_key,
            "holder_profile_path": holder.profile_document_key,
            "is_kyc": False,
            "is_terms_accepted": False,
            "status": STATUS_REGISTERED,
            "created_at": to_naive_iso(holder.created_at),
            "updated_at": to_naive_iso(holder.updated_at),
            "deleted_at": None,
            contact_key: holder.mobile,
        }

    async def update_profile(
        self, holder: Holder, changes: UpdateHolder
    ) -> dict[str, Any]:
        """Apply the fields present in ``changes``.

        A new profile image is stored, and the public DID profile
        document is rewritten with the name and the image, as the DCS
        does. The document is only rewritten together with a new image,
        because the previous image is not kept in a form it can embed.
        A changed name or contact number is reported to every linked
        DCS, in the same transaction.

        Raises:
            UnsupportedImageError: The image is not valid base64 PNG,
                JPEG or WebP, or is too large.
        """
        previous_details = (holder.full_name, holder.mobile)
        if changes.name is not None:
            holder.full_name = changes.name
        if changes.contact is not None:
            holder.mobile = changes.contact
        if changes.profile_image is not None:
            image_data_uri = await self._store_profile_image(
                holder, changes.profile_image
            )
            await self._rewrite_profile_document(holder, image_data_uri)
        if (holder.full_name, holder.mobile) != previous_details:
            await self.onboarding.queue_profile_report(holder.id)
        holder.updated_at = utc_now()
        self.audit.record(holder.id, AuditAction.PROFILE_UPDATED)
        await self.session.commit()
        return await self.build_detail(holder, contact_key="phone_number")

    async def _store_profile_image(
        self, holder: Holder, encoded_image: str
    ) -> str:
        try:
            content = base64.b64decode(encoded_image, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise UnsupportedImageError(
                "Image format not supported. Send PNG, JPEG or WebP as base64."
            ) from exc
        if len(content) > self.settings.max_profile_image_bytes:
            raise UnsupportedImageError(
                "The profile image must not be larger than "
                f"{self.settings.max_profile_image_bytes} bytes."
            )
        media_type = detect_image_type(content)
        if media_type is None:
            raise UnsupportedImageError(
                "Image format not supported. Send PNG, JPEG or WebP."
            )
        key = (
            f"holders/{holder.id}/profile-image."
            f"{_IMAGE_EXTENSIONS[media_type]}"
        )
        await self.storage.put(key, content, media_type)
        holder.profile_image_key = key
        return f"data:{media_type};base64,{encoded_image}"

    async def _rewrite_profile_document(
        self, holder: Holder, image_data_uri: str
    ) -> None:
        if not holder.profile_document_key:
            return
        # The phone number is left out on purpose: the document is
        # public, and the DCS publishing it was a privacy leak.
        document: dict[str, Any] = {
            "@context": DID_CONTEXTS[:1],
            "id": holder.did,
            "type": "HolderProfile",
            "name": holder.full_name,
            "image": image_data_uri,
            "created": holder.created_at.isoformat(),
        }
        await self.storage.put(
            holder.profile_document_key,
            json.dumps(document).encode(),
            "application/ld+json",
        )
