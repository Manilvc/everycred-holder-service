"""HTTP routes for the holder inbox and connector event webhooks."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, status

from app.core.signatures import DELIVERY_HEADER, SIGNATURE_HEADER
from app.features.auth.dependencies import CurrentHolder
from app.features.notifications.dependencies import (
    ConnectorEventServiceDep,
    InboxServiceDep,
)
from app.features.notifications.schemas import (
    EventReceipt,
    InboxNotificationResponse,
    InboxQueryParams,
)
from app.shared.schemas import ErrorResponse, Page
from app.shared.uploads import read_body_limited

inbox_router = APIRouter(prefix="/notifications", tags=["Notifications"])
connector_router = APIRouter(prefix="/connector", tags=["Connector Events"])

# Connector events are small JSON documents; anything bigger is refused
# before it is read into memory in full.
MAX_EVENT_BYTES = 16 * 1024


@inbox_router.get(
    "",
    response_model=Page[InboxNotificationResponse],
    summary="List my notifications",
)
async def list_notifications(
    holder: CurrentHolder,
    service: InboxServiceDep,
    query: Annotated[InboxQueryParams, Query()],
) -> Page[InboxNotificationResponse]:
    """Return the inbox, newest first."""
    return await service.list_notifications(
        holder.id,
        unread_only=query.unread_only,
        limit=query.limit,
        offset=query.offset,
    )


@inbox_router.post(
    "/{notification_id}/read",
    response_model=InboxNotificationResponse,
    summary="Mark a notification as read",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    holder: CurrentHolder,
    service: InboxServiceDep,
) -> InboxNotificationResponse:
    """Mark one notification as read."""
    return await service.mark_read(holder.id, notification_id)


@inbox_router.post(
    "/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark all notifications as read",
)
async def mark_all_notifications_read(
    holder: CurrentHolder, service: InboxServiceDep
) -> None:
    """Mark every notification as read."""
    await service.mark_all_read(holder.id)


@connector_router.post(
    "/events",
    response_model=EventReceipt,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a credential or request event from the connector",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
    },
)
async def receive_connector_event(
    request: Request,
    service: ConnectorEventServiceDep,
    signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER)] = None,
    delivery_id: Annotated[str | None, Header(alias=DELIVERY_HEADER)] = None,
) -> EventReceipt:
    """Record the event and queue the holder's notifications.

    Authenticated by the ``X-EveryCRED-Signature`` HMAC, not a token.
    Answers quickly; socket and push delivery happen in the worker. A
    repeated delivery id is acknowledged without notifying again.
    """
    raw_body = await read_body_limited(request, MAX_EVENT_BYTES)
    return await service.receive(raw_body, signature, delivery_id)
