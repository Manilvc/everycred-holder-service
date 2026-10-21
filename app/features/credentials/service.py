"""The holder's credentials, fetched live through the connector.

Nothing about a credential is stored here. Each call asks the connector,
which routes to the DCS source that issued it and only returns
credentials linked to the holder's email. Sharing, downloading, and
emailing are recorded in the audit trail by credential id only.
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.connector import (
    ConnectorClient,
    NormalizedCredential,
    OperationResponse,
)
from app.core.email import EmailDeliveryError, EmailSender, OutgoingEmail
from app.core.exceptions import ExternalServiceError, TooManyRequestsError
from app.core.models import utc_now
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.credentials.exceptions import (
    CredentialDocumentUnavailableError,
    CredentialNotShareableError,
)
from app.features.credentials.schemas import (
    CredentialListResponse,
    CredentialShareResponse,
)
from app.features.holders.models import Holder

_RESOURCE_TYPE = "credential"


class CredentialService:
    """Credential reads and sharing actions for one holder.

    Attributes:
        session: Unit of work; used for audit entries and rate limits.
        settings: Credential email rate limit.
        connector: Client for the connector service.
        mailer: Sends credential links by email.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        connector: ConnectorClient,
        mailer: EmailSender,
    ) -> None:
        self.session = session
        self.settings = settings
        self.connector = connector
        self.mailer = mailer
        self.audit = AuditRepository(session)

    async def list_credentials(self, holder: Holder) -> CredentialListResponse:
        """Return the holder's credentials from every source."""
        lookup = await self.connector.lookup_credentials(holder.email)
        return CredentialListResponse(items=lookup.items)

    async def get_credential(
        self, holder: Holder, credential_id: str
    ) -> NormalizedCredential:
        """Return one of the holder's credentials.

        Raises:
            NotFoundError: The credential does not exist or is not the
                holder's.
        """
        return await self.connector.get_credential(holder.email, credential_id)

    async def share_credential(
        self, holder: Holder, credential_id: str
    ) -> CredentialShareResponse:
        """Return the public link and QR code of a credential.

        Raises:
            CredentialNotShareableError: The source gave no public link.
        """
        credential = await self.get_credential(holder, credential_id)
        if not credential.credential_url:
            raise CredentialNotShareableError(
                "This credential has no link that can be shared."
            )
        await self._record(holder, AuditAction.CREDENTIAL_SHARED, credential)
        return CredentialShareResponse(
            credential_id=credential.credential_id,
            source_code=credential.source_code,
            title=credential.title,
            share_url=credential.credential_url,
            qr_code_url=credential.qr_code_url,
        )

    async def download_credential(
        self, holder: Holder, credential_id: str
    ) -> NormalizedCredential:
        """Return a credential whose W3C document is available.

        Raises:
            CredentialDocumentUnavailableError: The source returned no
                credential document.
        """
        credential = await self.get_credential(holder, credential_id)
        if credential.credential_json is None:
            raise CredentialDocumentUnavailableError(
                "The credential document is not available."
            )
        await self._record(
            holder, AuditAction.CREDENTIAL_DOWNLOADED, credential
        )
        return credential

    async def email_credential(
        self,
        holder: Holder,
        credential_id: str,
        recipient_email: str,
        note: str | None,
    ) -> None:
        """Email a link to the credential, within the hourly limit.

        Raises:
            TooManyRequestsError: The holder reached
                ``CREDENTIAL_EMAIL_HOURLY_LIMIT``.
            CredentialNotShareableError: The source gave no public link.
            ExternalServiceError: The email could not be sent.
        """
        sent_last_hour = await self.audit.count_since(
            holder.id,
            AuditAction.CREDENTIAL_EMAILED,
            utc_now() - timedelta(hours=1),
        )
        if sent_last_hour >= self.settings.credential_email_hourly_limit:
            raise TooManyRequestsError(
                "Too many credentials emailed. Try again later."
            )
        credential = await self.get_credential(holder, credential_id)
        if not credential.credential_url:
            raise CredentialNotShareableError(
                "This credential has no link that can be shared."
            )
        lines = [
            f"{holder.full_name} shared a verifiable credential with you"
            + (f": {credential.title}." if credential.title else "."),
            f"View and verify it here: {credential.credential_url}",
        ]
        if note:
            lines.append(f"\nMessage from the sender:\n{note}")
        try:
            await self.mailer.send(
                OutgoingEmail(
                    recipient=recipient_email,
                    subject="A credential was shared with you",
                    body="\n".join(lines),
                )
            )
        except EmailDeliveryError as exc:
            raise ExternalServiceError(
                "The email could not be sent. Try again later."
            ) from exc
        await self._record(holder, AuditAction.CREDENTIAL_EMAILED, credential)

    async def get_verification_stats(
        self, holder: Holder, source_code: str, credential_id: str
    ) -> OperationResponse:
        """Return how often and where a credential was verified."""
        return await self.connector.run_operation(
            holder.email,
            "credentials.stats",
            source_code=source_code,
            params={"credential_id": credential_id},
        )

    async def _record(
        self,
        holder: Holder,
        action: AuditAction,
        credential: NormalizedCredential,
    ) -> None:
        self.audit.record(
            holder.id,
            action,
            resource_type=_RESOURCE_TYPE,
            resource_id=f"{credential.source_code}:{credential.credential_id}",
        )
        await self.session.commit()
