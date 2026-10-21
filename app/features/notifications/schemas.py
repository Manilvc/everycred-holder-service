"""Request and response models for notifications and connector events."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.shared.pagination import PaginationParams

ConnectorEventType = Literal[
    "credential.issued",
    "credential.revoked",
    "request.created",
    "request.updated",
]


class ConnectorEventData(BaseModel):
    """What the event is about. Unknown fields are ignored."""

    source_code: str = Field(max_length=64)
    holder_email: EmailStr
    credential_id: str | None = Field(default=None, max_length=255)
    request_id: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=64)


class ConnectorEventPayload(BaseModel):
    """Body of a webhook sent by the connector."""

    id: str = Field(max_length=128)
    event: ConnectorEventType
    created_at: datetime
    data: ConnectorEventData


class EventReceipt(BaseModel):
    """What the service did with a received event."""

    status: Literal["accepted", "duplicate", "ignored"]


class InboxQueryParams(PaginationParams):
    """Query string of the inbox list: pagination plus a read filter."""

    unread_only: bool = False


class InboxNotificationResponse(BaseModel):
    """One inbox entry, shaped like the DCS holder inbox payload."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    notification_type: str
    title: str
    message: str
    redirect_module: str | None
    redirect_path: str | None
    redirect_entity_type: str | None
    redirect_entity_id: str | None
    extra_metadata: dict[str, Any] | None
    is_read: bool
    created_at: datetime
