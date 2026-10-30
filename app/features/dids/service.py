"""Holder DIDs: provisioning, device keys, and DID documents.

A holder DID is ``<DID_PREFIX>:<uuid4>``, created at registration with
a QR code of the DID and a small JSON-LD profile document, both kept in
object storage. The wallet then generates key pairs on the device and
registers the public halves here; they are published as verification
methods in the DID document served by :meth:`DidService.resolve`.
"""

import io
import json
import logging
import secrets
import uuid
from dataclasses import dataclass

import qrcode
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.models import utc_now
from app.core.storage import ObjectStorage
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.dids.exceptions import (
    DidNotFoundError,
    HolderKeyLimitError,
    HolderKeyNotFoundError,
)
from app.features.dids.models import HolderKey
from app.features.dids.repository import HolderKeyRepository
from app.features.dids.schemas import (
    DidDocument,
    HolderKeyResponse,
    PublicJwk,
    VerificationMethod,
)
from app.features.holders.models import Holder
from app.features.holders.repository import HolderRepository

logger = logging.getLogger(__name__)

DID_CONTEXTS = [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/suites/jws-2020/v1",
]


@dataclass(frozen=True, slots=True)
class ProvisionedDid:
    """A new DID and the storage keys of its files."""

    did: str
    qr_code_key: str
    profile_document_key: str


def _render_qr_png(content: str) -> bytes:
    image = qrcode.make(content)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class DidProvisioner:
    """Creates a holder's DID and uploads its QR code and profile.

    Attributes:
        storage: Where the QR code and profile document are written.
        settings: Source of the DID prefix.
    """

    def __init__(self, storage: ObjectStorage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings

    async def provision(self, holder_id: uuid.UUID) -> ProvisionedDid:
        """Generate a DID for ``holder_id`` and store its files."""
        did = f"{self.settings.did_prefix}:{uuid.uuid4()}"
        qr_code_key = f"holders/{holder_id}/did/qr-code.png"
        profile_document_key = f"holders/{holder_id}/did/profile.json"
        # The profile is public metadata about the DID, so it carries no
        # personal data such as the holder's name or email.
        profile_document = {
            "@context": DID_CONTEXTS[:1],
            "id": did,
            "type": "HolderProfile",
            "created": utc_now().isoformat(),
        }
        qr_png = await run_in_threadpool(_render_qr_png, did)
        await self.storage.put(qr_code_key, qr_png, "image/png")
        await self.storage.put(
            profile_document_key,
            json.dumps(profile_document).encode(),
            "application/ld+json",
        )
        return ProvisionedDid(did, qr_code_key, profile_document_key)


class DidService:
    """Manages a holder's device keys and resolves DID documents.

    Attributes:
        session: Unit of work; the service commits its own changes.
        settings: Source of the per-holder key limit.
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.keys = HolderKeyRepository(session)
        self.holders = HolderRepository(session)
        self.audit = AuditRepository(session)

    async def register_key(
        self, holder: Holder, public_jwk: PublicJwk
    ) -> HolderKeyResponse:
        """Publish a device-generated public key in the holder's DID.

        Raises:
            HolderKeyLimitError: The holder already has the maximum
                number of active keys.
        """
        active_count = await self.keys.count_active(holder.id)
        if active_count >= self.settings.max_keys_per_holder:
            raise HolderKeyLimitError(
                "Revoke an existing key before registering another."
            )
        key = HolderKey(
            holder_id=holder.id,
            key_id=f"key-{secrets.token_hex(8)}",
            algorithm=public_jwk.algorithm,
            public_jwk=public_jwk.model_dump(exclude_none=True),
        )
        self.keys.add(key)
        self.audit.record(
            holder.id,
            AuditAction.KEY_REGISTERED,
            resource_type="key",
            resource_id=key.key_id,
        )
        await self.session.commit()
        logger.info("Holder %s registered key %s", holder.id, key.key_id)
        return self._to_response(holder.did, key)

    async def list_keys(self, holder: Holder) -> list[HolderKeyResponse]:
        """Return the holder's active keys."""
        keys = await self.keys.list_active(holder.id)
        return [self._to_response(holder.did, key) for key in keys]

    async def revoke_key(self, holder: Holder, key_id: str) -> None:
        """Remove a key from the holder's DID document.

        Raises:
            HolderKeyNotFoundError: The holder has no active key
                ``key_id``.
        """
        key = await self.keys.get_active(holder.id, key_id)
        if key is None:
            raise HolderKeyNotFoundError(f"Key {key_id} does not exist.")
        key.revoked_at = utc_now()
        self.audit.record(
            holder.id,
            AuditAction.KEY_REVOKED,
            resource_type="key",
            resource_id=key_id,
        )
        await self.session.commit()

    async def resolve(self, did: str) -> DidDocument:
        """Return the DID document of an active holder.

        Raises:
            DidNotFoundError: No active holder owns ``did``.
        """
        holder = await self.holders.get_by_did(did)
        if holder is None or not holder.is_active or holder.is_deleted:
            raise DidNotFoundError("The DID was not found.")
        keys = await self.keys.list_active(holder.id)
        methods = [
            VerificationMethod(
                id=f"{did}#{key.key_id}",
                controller=did,
                public_key_jwk=key.public_jwk,
            )
            for key in keys
        ]
        method_ids = [method.id for method in methods]
        return DidDocument(
            context=DID_CONTEXTS,
            id=did,
            verification_method=methods,
            authentication=method_ids,
            assertion_method=method_ids,
        )

    @staticmethod
    def _to_response(did: str, key: HolderKey) -> HolderKeyResponse:
        return HolderKeyResponse(
            key_id=key.key_id,
            verification_method_id=f"{did}#{key.key_id}",
            algorithm=key.algorithm,
            public_jwk=key.public_jwk,
            created_at=key.created_at,
        )
