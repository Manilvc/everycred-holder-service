"""Inbox texts and wallet redirects for each connector event.

``notification_type``, ``redirect_module`` and the redirect paths are a
contract with the wallet app, taken from the DCS holder notification
registry so the app handles notifications from this service exactly as
it handles those from DCS. Never rename a value.

Connector events carry ids only, not issuer or subject names, so the
texts are generic; the wallet loads details when the holder opens one.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from app.features.notifications.models import InboxNotification
from app.features.notifications.schemas import ConnectorEventPayload

REDIRECT_MODULE_CREDENTIALS = "credentials"
REDIRECT_MODULE_REQUESTS = "requests"


@dataclass(frozen=True, slots=True)
class _MessageSpec:
    notification_type: str
    title: str
    message: str


_CREDENTIAL_SPECS = {
    "credential.issued": _MessageSpec(
        "credential_issued",
        "New Credential Received",
        "You received a new credential.",
    ),
    "credential.revoked": _MessageSpec(
        "credential_revoked",
        "Credential Revoked",
        "One of your credentials was revoked.",
    ),
}
_NEW_REQUEST_SPEC = _MessageSpec(
    "new_credential_request",
    "New credential request",
    "You have a new credential request.",
)
_REQUEST_STATUS_SPECS = {
    "approved": _MessageSpec(
        "credential_request_approved",
        "Request Approved",
        "Your credential request was approved.",
    ),
    "declined": _MessageSpec(
        "credential_request_declined",
        "Request Declined",
        "Your credential request was declined.",
    ),
}
_REQUEST_UPDATED_SPEC = _MessageSpec(
    "credential_request_updated",
    "Request Updated",
    "One of your credential requests was updated.",
)


def _spec_for(payload: ConnectorEventPayload) -> _MessageSpec:
    if payload.event in _CREDENTIAL_SPECS:
        return _CREDENTIAL_SPECS[payload.event]
    if payload.event == "request.created":
        return _NEW_REQUEST_SPEC
    return _REQUEST_STATUS_SPECS.get(
        (payload.data.status or "").lower(), _REQUEST_UPDATED_SPEC
    )


def build_inbox_notification(
    payload: ConnectorEventPayload,
    holder_id: uuid.UUID,
    redirect_base_url: str,
) -> InboxNotification:
    """Return the inbox row a connector event produces for a holder."""
    spec = _spec_for(payload)
    data = payload.data
    is_credential_event = payload.event.startswith("credential.")
    if is_credential_event:
        module, entity_type, path_prefix, metadata_key = (
            REDIRECT_MODULE_CREDENTIALS,
            "credential",
            "credential",
            "credential_id",
        )
        entity_id = data.credential_id
    else:
        module, entity_type, path_prefix, metadata_key = (
            REDIRECT_MODULE_REQUESTS,
            "issuer_request",
            "request",
            "request_id",
        )
        entity_id = data.request_id
    path = f"{path_prefix}/{entity_id}"
    metadata: dict[str, Any] = {"source_code": data.source_code}
    if entity_id:
        metadata[metadata_key] = entity_id
    return InboxNotification(
        id=uuid.uuid4(),
        holder_id=holder_id,
        notification_type=spec.notification_type,
        title=spec.title,
        message=spec.message,
        redirect_module=module,
        redirect_path=f"{redirect_base_url}{path}" if entity_id else None,
        redirect_entity_type=entity_type if entity_id else None,
        redirect_entity_id=entity_id,
        extra_metadata=metadata,
        is_read=False,
    )


def to_wallet_payload(notification: InboxNotification) -> dict[str, Any]:
    """Return the payload sent over socket and push for a notification."""
    return {
        "uuid": str(notification.id),
        "notification_type": notification.notification_type,
        "title": notification.title,
        "message": notification.message,
        "redirect_module": notification.redirect_module,
        "redirect_path": notification.redirect_path,
        "redirect_entity_type": notification.redirect_entity_type,
        "redirect_entity_id": notification.redirect_entity_id,
        "extra_metadata": notification.extra_metadata,
    }
