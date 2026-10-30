"""Credential endpoints in the DCS shape, served through the connector.

Nothing about a credential is stored here. Each call asks the connector,
which routes to the DCS source that issued it and only returns
credentials linked to the holder's email. The only rows written are
:class:`~app.features.credentials.models.CredentialRef` references,
which give every credential the integer ``id`` the wallet app expects.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.connector import (
    ConnectorClient,
    CredentialLookupItem,
    NormalizedCredential,
)
from app.core.email import EmailDeliveryError, EmailSender, OutgoingEmail
from app.core.exceptions import (
    AppError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.models import to_naive_iso, utc_now
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.credentials.models import CredentialRef
from app.features.credentials.repository import CredentialRefRepository
from app.features.credentials.schemas import (
    CredentialType,
    VerificationAnalyticsRequest,
)
from app.features.holders.models import Holder

logger = logging.getLogger(__name__)

DETAILS_NOT_FOUND = "Details not found!"
CREDENTIAL_NOT_FOUND = "Credential does not found from the given id!"
INVALID_FILE = "Invalid file!"
FAILED_TO_SEND_MAIL = "Failed to send mail"
# The connector carries field values, not their types; plain text is
# what every wallet field renderer can show.
DEFAULT_FIELD_TYPE = "text"
# DCS preview dates look like "2026-01-05 03:30 pm".
_PREVIEW_TIME_FORMAT = "%Y-%m-%d %I:%M %p"


class UpstreamAnswerError(AppError):
    """Raised to pass a DCS error status and message to the wallet."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_revoked(item: CredentialLookupItem) -> bool:
    credential = item.credential
    return item.status == "revoked" or (
        credential is not None and credential.status == "revoked"
    )


def _matches_type(
    item: CredentialLookupItem, credential_type: CredentialType, now: datetime
) -> bool:
    if credential_type is CredentialType.REVOKED:
        return _is_revoked(item)
    if _is_revoked(item):
        return False
    valid_until = _parse_time(
        item.credential.valid_until if item.credential else None
    )
    is_expired = valid_until is not None and valid_until < now
    return is_expired == (credential_type is CredentialType.EXPIRED)


def _issued_at(item: CredentialLookupItem) -> datetime | None:
    issued = item.credential.issued_at if item.credential else None
    return _parse_time(issued) or item.first_seen_at


def _newest_first(item: CredentialLookupItem) -> datetime:
    return (
        item.first_seen_at
        or _issued_at(item)
        or datetime.min.replace(tzinfo=UTC)
    )


def _paginate(
    rows: list[dict[str, Any]], page: int, per_page: int
) -> list[dict[str, Any]]:
    start = (max(page, 1) - 1) * per_page
    return rows[start : start + per_page]


def _preview_time(value: str | None) -> str | None:
    parsed = _parse_time(value)
    if parsed is None:
        return value
    return parsed.strftime(_PREVIEW_TIME_FORMAT).lower()


class CredentialService:
    """Credential reads for one holder, plus the public lookups.

    Attributes:
        session: Unit of work; used for references and audit entries.
        settings: Verifier URL used in share links.
        connector: Client for the connector service.
        mailer: Sends credentials the holder emails to someone.
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
        self.refs = CredentialRefRepository(session)
        self.audit = AuditRepository(session)

    async def list_credentials(
        self,
        holder: Holder,
        holder_numeric_id: int,
        credential_type: CredentialType,
        page: int,
        per_page: int,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Return one bucket of the holder's credentials, newest first.

        With ``per_page`` 0 every row is returned as a plain list, as
        the DCS does.

        Raises:
            PermissionDeniedError: ``holder_numeric_id`` is someone else.
            NotFoundError: The bucket is empty. The DCS answers 404 with
                ``data`` set, and the app relies on that.
        """
        if holder_numeric_id != holder.numeric_id:
            raise PermissionDeniedError(
                "You can only view your own credentials."
            )
        lookup = await self.connector.lookup_credentials(holder.email)
        refs = await self._references(holder, lookup.items)
        now = utc_now()
        matching = sorted(
            (
                (item, item.credential)
                for item in lookup.items
                if item.credential is not None
                and _matches_type(item, credential_type, now)
            ),
            key=lambda pair: _newest_first(pair[0]),
            reverse=True,
        )
        rows = [
            self._row(
                holder,
                item,
                credential,
                refs[(item.source_code, item.credential_id)],
            )
            for item, credential in matching
        ]
        if not rows:
            raise NotFoundError(
                DETAILS_NOT_FOUND,
                data={"data": [], "pages": page, "total": 0},
            )
        if per_page == 0:
            return rows
        return {
            "data": _paginate(rows, page, per_page),
            "pages": page,
            "total": len(rows),
        }

    async def share_credential(
        self, holder: Holder, numeric_id: int
    ) -> dict[str, Any]:
        """Return what the wallet needs to share a credential.

        Raises:
            NotFoundError: The id is not one of the holder's credentials.
        """
        ref, credential = await self._owned_credential(holder, numeric_id)
        has_qr = bool(credential.qr_code_url)
        self._record(holder, AuditAction.CREDENTIAL_SHARED, ref)
        await self.session.commit()
        return {
            "name": credential.holder_name,
            "viewer_link": self._viewer_link(ref, credential),
            "qr_image": credential.qr_code_url or "",
            "is_verifiable": has_qr,
            "download_link": credential.credential_url,
            "logo_image": credential.subject_logo_url,
            "subject_name": credential.subject_name or credential.title,
        }

    async def preview_credential(
        self, holder: Holder, numeric_id: int
    ) -> dict[str, Any]:
        """Return the credential's fields in the DCS preview shape.

        Field types are not carried by the connector, so every field is
        reported as ``text``; date values arrive already formatted by
        the issuing DCS. ``verification_count`` is ``None``: the count
        lives in the DCS and is served by ``GET /v1/holder/stats``.

        Raises:
            NotFoundError: The id is not one of the holder's credentials.
        """
        _, credential = await self._owned_credential(holder, numeric_id)
        return {
            "valid_from": _preview_time(credential.valid_from),
            "valid_until": _preview_time(credential.valid_until),
            "revoked": credential.status == "revoked",
            "verification_count": None,
            "subject_name": credential.subject_name or credential.title,
            "logo_image": credential.subject_logo_url,
            "credential_data": [
                {"fname": name, "fvalue": value, "ftype": DEFAULT_FIELD_TYPE}
                for name, value in credential.fields.items()
            ],
        }

    async def download_credential(
        self, holder: Holder, numeric_id: int
    ) -> dict[str, Any]:
        """Return the link to the credential document.

        The DCS copied the file into a per-holder download folder first;
        the issuing DCS already serves the document, so its link is
        returned as is.

        Raises:
            NotFoundError: The id is not one of the holder's credentials.
            AppError: The source has no document for the credential.
        """
        ref, credential = await self._owned_credential(holder, numeric_id)
        if not credential.credential_url:
            raise AppError(INVALID_FILE)
        self._record(holder, AuditAction.CREDENTIAL_DOWNLOADED, ref)
        await self.session.commit()
        return {"credential": credential.credential_url}

    async def email_credential(
        self, holder: Holder, numeric_id: int, recipients: list[str]
    ) -> None:
        """Email the credential's verifier link to each recipient.

        Raises:
            NotFoundError: The id is not one of the holder's credentials.
            AppError: Too many recipients, or an email was not sent.
        """
        limit = self.settings.max_share_recipients
        if len(recipients) > limit:
            raise AppError(
                f"A credential can be emailed to at most {limit} "
                "addresses at once."
            )
        ref, credential = await self._owned_credential(holder, numeric_id)
        message = self._share_email_body(holder, ref, credential)
        subject = f"{credential.subject_name or credential.title} Is Shared"
        try:
            await asyncio.gather(
                *(
                    self.mailer.send(
                        OutgoingEmail(
                            recipient=recipient, subject=subject, body=message
                        )
                    )
                    for recipient in dict.fromkeys(recipients)
                )
            )
        except EmailDeliveryError as exc:
            raise AppError(FAILED_TO_SEND_MAIL) from exc
        self._record(holder, AuditAction.CREDENTIAL_EMAILED, ref)
        await self.session.commit()
        logger.info(
            "Holder %s emailed a credential to %d recipient(s)",
            holder.id,
            len(recipients),
        )

    async def get_stats(
        self, holder: Holder, numeric_id: int
    ) -> tuple[int, str, Any]:
        """Return the source's verification statistics for a credential.

        Returns:
            The source's HTTP status, message and ``data``, passed on.

        Raises:
            NotFoundError: The id is not one of the holder's credentials.
        """
        ref = await self.refs.get(holder.id, numeric_id)
        if ref is None:
            raise NotFoundError(DETAILS_NOT_FOUND)
        response = await self.connector.run_operation(
            holder.email,
            "credentials.stats",
            source_code=ref.source_code,
            params={"credential_id": ref.credential_id},
        )
        result = response.items[0]
        if result.status_code == 404:
            raise NotFoundError(DETAILS_NOT_FOUND)
        if not result.ok:
            raise UpstreamAnswerError(
                result.status_code,
                result.message or "The statistics could not be loaded.",
            )
        return (
            result.status_code,
            result.message or "Information retrieved successfully!",
            result.data,
        )

    async def list_notifications(
        self, holder: Holder, page: int, per_page: int
    ) -> dict[str, Any]:
        """Return issue and revoke events built from the credentials.

        Like the DCS, every credential gives an "issued" item and a
        revoked one also a "revoked" item. Items carry both the DCS keys
        and the ones the app reads (``credential``, ``issuer_name``,
        ``created_at``).
        """
        lookup = await self.connector.lookup_credentials(holder.email)
        events: list[tuple[datetime, dict[str, Any]]] = []
        for item in lookup.items:
            credential = item.credential
            if credential is None:
                continue
            common = {
                "credential_image": credential.image_url,
                "credential": credential.subject_name or credential.title,
                "issuer_name": credential.issuer.name,
            }
            issued_at = _issued_at(item) or utc_now()
            events.append(
                (
                    issued_at,
                    {
                        "type": "issued",
                        **common,
                        "issued_at": to_naive_iso(issued_at),
                        "created_at": to_naive_iso(issued_at),
                    },
                )
            )
            if _is_revoked(item):
                revoked_at = item.status_changed_at or issued_at
                events.append(
                    (
                        revoked_at,
                        {
                            "type": "revoked",
                            **common,
                            "revoked_at": to_naive_iso(revoked_at),
                            "created_at": to_naive_iso(revoked_at),
                        },
                    )
                )
        events.sort(key=lambda event: event[0], reverse=True)
        items = [event for _, event in events]
        start = (max(page, 1) - 1) * per_page
        return {
            "data": items[start : start + per_page],
            "pages": page,
            "total": len(items),
        }

    async def get_public_credential(
        self, credential_unique_id: str
    ) -> dict[str, Any]:
        """Return any credential in the DCS public verifier shape.

        Raises:
            NotFoundError: The connector does not know the credential.
        """
        try:
            credential = await self.connector.get_public_credential(
                credential_unique_id
            )
        except NotFoundError as exc:
            raise NotFoundError(CREDENTIAL_NOT_FOUND) from exc
        return {
            "issuer_description": credential.issuer.description,
            "holder_name": credential.holder_name,
            "theme_type": None,
            "not_draft": True,
            "subject_logo_link": credential.subject_logo_url,
            "title": credential.title,
            "issued_date": credential.issued_at,
            "issuer_logo_link": credential.issuer.logo_url,
            "issuer_name": credential.issuer.name,
            "issuer_email": credential.issuer.email,
            "issuer_did": credential.issuer.did,
            "fields": credential.fields,
            "credential_link": credential.credential_url,
            "credential_image_path": credential.image_url,
            "credential_unique_id": (
                credential.credential_unique_id or credential.credential_id
            ),
            "qrcode": credential.qr_code_url or "",
            "last_verified": None,
            "is_revoked": credential.status == "revoked",
            "hash": credential.hash,
            "bn_credential": True,
            "credential_json_content": self._raw_document(credential),
            "subject_name": credential.subject_name,
            "badge_title": None,
            "badge_logo": None,
        }

    async def record_verification(
        self, credential_unique_id: str, payload: VerificationAnalyticsRequest
    ) -> tuple[int, str, Any]:
        """Pass a verification record to the credential's source.

        Raises:
            NotFoundError: The connector does not know the credential.
            UpstreamAnswerError: The source refused the record.
        """
        try:
            result = await self.connector.record_verification(
                credential_unique_id, payload.model_dump(exclude_unset=True)
            )
        except NotFoundError as exc:
            raise NotFoundError(CREDENTIAL_NOT_FOUND) from exc
        if not result.ok:
            raise UpstreamAnswerError(
                result.status_code,
                result.message or "The verification could not be recorded.",
            )
        return 201, "Information stored successfully", result.data

    async def _references(
        self, holder: Holder, items: list[CredentialLookupItem]
    ) -> dict[tuple[str, str], CredentialRef]:
        refs = await self.refs.ensure(
            holder.id,
            [(item.source_code, item.credential_id) for item in items],
        )
        await self.session.commit()
        return refs

    async def _owned_credential(
        self, holder: Holder, numeric_id: int
    ) -> tuple[CredentialRef, NormalizedCredential]:
        ref = await self.refs.get(holder.id, numeric_id)
        if ref is None:
            raise NotFoundError(DETAILS_NOT_FOUND)
        try:
            credential = await self.connector.get_credential(
                holder.email, ref.credential_id
            )
        except NotFoundError as exc:
            raise NotFoundError(DETAILS_NOT_FOUND) from exc
        return ref, credential

    def _record(
        self, holder: Holder, action: AuditAction, ref: CredentialRef
    ) -> None:
        self.audit.record(
            holder.id,
            action,
            resource_type="credential",
            resource_id=f"{ref.source_code}:{ref.credential_id}",
        )

    def _viewer_link(
        self, ref: CredentialRef, credential: NormalizedCredential
    ) -> str:
        # Credentials without a QR code (jsonWebSignature2020) cannot be
        # verified, so they get no verifier link, as in the DCS.
        if not credential.qr_code_url:
            return ""
        unique_id = credential.credential_unique_id or ref.credential_id
        return f"{self.settings.verifier_base_url}{unique_id}"

    def _share_email_body(
        self,
        holder: Holder,
        ref: CredentialRef,
        credential: NormalizedCredential,
    ) -> str:
        lines = [
            f"{credential.holder_name or holder.full_name} shared a "
            "credential with you.",
            f"Credential: {credential.subject_name or credential.title}",
            f"Issued by: {credential.issuer.name or 'Unknown issuer'}",
            "Credential ID: "
            f"{credential.credential_unique_id or ref.credential_id}",
        ]
        viewer_link = self._viewer_link(ref, credential)
        if viewer_link:
            lines.append(f"View and verify it: {viewer_link}")
        return "\n".join(lines)

    @staticmethod
    def _raw_document(credential: NormalizedCredential) -> str | None:
        # The original string keeps proofs checkable; re-serialising the
        # parsed document is only a fallback for sources that lack it.
        if credential.credential_json_content:
            return credential.credential_json_content
        if credential.credential_json is not None:
            return json.dumps(credential.credential_json)
        return None

    @staticmethod
    def _row(
        holder: Holder,
        item: CredentialLookupItem,
        credential: NormalizedCredential,
        ref: CredentialRef,
    ) -> dict[str, Any]:
        revoked = _is_revoked(item)
        created_at = _issued_at(item)
        return {
            "id": ref.numeric_id,
            "uuid": item.credential_id,
            "source_code": item.source_code,
            "candidate_name": credential.holder_name,
            "candidate_email": holder.email,
            "credential_path": credential.credential_url,
            "credential_unique_id": (
                credential.credential_unique_id or item.credential_id
            ),
            "credential_image_path": credential.image_url,
            "qrcode_path": credential.qr_code_url,
            "hash": credential.hash,
            "revoked": revoked,
            "revoked_at": (
                to_naive_iso(item.status_changed_at) if revoked else None
            ),
            "valid_from": credential.valid_from,
            "valid_until": credential.valid_until,
            "is_issued": True,
            "created_at": to_naive_iso(created_at),
            "updated_at": to_naive_iso(item.status_changed_at),
            "deleted_at": None,
            "logo": credential.subject_logo_url,
            "subject_name": credential.subject_name or credential.title,
            "issuer_name": credential.issuer.name,
            "issuer_logo": credential.issuer.logo_url,
        }
