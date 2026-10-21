"""Holder inbox, connector event intake, and outbox delivery.

The connector tells this service when a credential is issued or
revoked, or a credential request changes. :class:`ConnectorEventService`
verifies the webhook, writes an inbox entry, and queues one outbox row
per live channel, all in one transaction, then answers at once. The
background worker sends the outbox through
:class:`NotificationDeliveryService`, retrying with backoff.
"""

import logging
import uuid
from collections import defaultdict
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.models import utc_now
from app.core.signatures import is_signature_valid
from app.features.devices.models import PushToken
from app.features.devices.repository import PushTokenRepository
from app.features.holders.repository import HolderRepository
from app.features.notifications.channels import (
    PushMessage,
    PushSender,
    SocketPublisher,
    to_push_data,
)
from app.features.notifications.exceptions import (
    InvalidEventError,
    InvalidEventSignatureError,
    NotificationNotFoundError,
)
from app.features.notifications.messages import (
    build_inbox_notification,
    to_wallet_payload,
)
from app.features.notifications.models import (
    ConnectorEvent,
    DeliveryChannel,
    DeliveryStatus,
    InboxNotification,
    NotificationDelivery,
)
from app.features.notifications.repository import NotificationRepository
from app.features.notifications.schemas import (
    ConnectorEventPayload,
    EventReceipt,
    InboxNotificationResponse,
)
from app.shared.schemas import Page

logger = logging.getLogger(__name__)

# Wait before retry n (1-based); the last value repeats.
RETRY_BACKOFF_SECONDS = (30, 120, 600, 1800, 3600)
_MAX_ERROR_LENGTH = 255


class InboxService:
    """Lists and marks a holder's inbox notifications.

    Attributes:
        session: Unit of work; the service commits its own changes.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.notifications = NotificationRepository(session)

    async def list_notifications(
        self,
        holder_id: uuid.UUID,
        *,
        unread_only: bool,
        limit: int,
        offset: int,
    ) -> Page[InboxNotificationResponse]:
        """Return one page of the inbox, newest first."""
        rows, total = await self.notifications.list_inbox(
            holder_id, unread_only=unread_only, limit=limit, offset=offset
        )
        return Page[InboxNotificationResponse](
            items=[
                InboxNotificationResponse.model_validate(row) for row in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def mark_read(
        self, holder_id: uuid.UUID, notification_id: uuid.UUID
    ) -> InboxNotificationResponse:
        """Mark one notification as read.

        Raises:
            NotificationNotFoundError: The holder has no such
                notification.
        """
        notification = await self.notifications.get_for_holder(
            holder_id, notification_id
        )
        if notification is None:
            raise NotificationNotFoundError("The notification was not found.")
        notification.is_read = True
        await self.session.commit()
        return InboxNotificationResponse.model_validate(notification)

    async def mark_all_read(self, holder_id: uuid.UUID) -> None:
        """Mark every notification of the holder as read."""
        await self.notifications.mark_all_read(holder_id)
        await self.session.commit()


class ConnectorEventService:
    """Accepts signed connector webhooks and queues notifications.

    Attributes:
        session: Unit of work; the service commits its own changes.
        settings: Shared secret, replay tolerance, redirect base URL.
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.notifications = NotificationRepository(session)
        self.holders = HolderRepository(session)

    async def receive(
        self,
        raw_body: bytes,
        signature: str | None,
        delivery_id: str | None,
    ) -> EventReceipt:
        """Verify, de-duplicate, and record one connector event.

        The signature is checked over the raw bytes before the body is
        parsed, so nothing unauthenticated is ever interpreted.

        Raises:
            InvalidEventSignatureError: Missing, wrong, or stale
                signature.
            InvalidEventError: The delivery id or body is unusable.
        """
        if not signature or not is_signature_valid(
            self.settings.connector_webhook_secret.get_secret_value(),
            signature,
            raw_body,
            self.settings.webhook_tolerance_seconds,
        ):
            raise InvalidEventSignatureError("The signature is invalid.")
        if not delivery_id or len(delivery_id) > 128:
            raise InvalidEventError("A valid delivery id is required.")
        try:
            payload = ConnectorEventPayload.model_validate_json(raw_body)
        except ValidationError as exc:
            raise InvalidEventError("The event body is invalid.") from exc

        if await self.notifications.has_event(delivery_id):
            return EventReceipt(status="duplicate")

        holder = await self.holders.get_by_email(payload.data.holder_email)
        self.notifications.add(
            ConnectorEvent(
                delivery_id=delivery_id,
                event=payload.event,
                source_code=payload.data.source_code,
                holder_id=holder.id if holder else None,
            )
        )
        if holder is not None:
            self._queue_notification(payload, holder.id)
        try:
            await self.session.commit()
        except IntegrityError:
            # The same delivery arrived twice at once; the other request
            # recorded it.
            await self.session.rollback()
            return EventReceipt(status="duplicate")
        if holder is None:
            logger.info(
                "Connector event %s has no matching holder", delivery_id
            )
            return EventReceipt(status="ignored")
        logger.info(
            "Connector event %s (%s) queued for holder %s",
            delivery_id,
            payload.event,
            holder.id,
        )
        return EventReceipt(status="accepted")

    def _queue_notification(
        self, payload: ConnectorEventPayload, holder_id: uuid.UUID
    ) -> None:
        notification = build_inbox_notification(
            payload, holder_id, self.settings.notification_redirect_base_url
        )
        self.notifications.add(notification)
        now = utc_now()
        for channel in DeliveryChannel:
            self.notifications.add(
                NotificationDelivery(
                    notification_id=notification.id,
                    holder_id=holder_id,
                    channel=channel.value,
                    next_attempt_at=now,
                )
            )


class NotificationDeliveryService:
    """Sends due outbox rows over socket and push. Used by the worker.

    Attributes:
        session: Unit of work; the service commits its own changes.
        settings: Maximum delivery attempts.
        socket_publisher: Socket channel, or None when not configured.
        push_sender: Push channel, or None when not configured.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        socket_publisher: SocketPublisher | None,
        push_sender: PushSender | None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.socket_publisher = socket_publisher
        self.push_sender = push_sender
        self.notifications = NotificationRepository(session)
        self.push_tokens = PushTokenRepository(session)

    async def deliver_due(self, batch_size: int) -> int:
        """Attempt every due delivery in one batch; return how many ran."""
        now = utc_now()
        due = await self.notifications.list_due_deliveries(now, batch_size)
        if not due:
            return 0
        push_holder_ids = {
            delivery.holder_id
            for delivery, _ in due
            if delivery.channel == DeliveryChannel.PUSH.value
        }
        tokens_by_holder: dict[uuid.UUID, list[PushToken]] = defaultdict(list)
        if self.push_sender is not None:
            for push_token in await self.push_tokens.list_active_for_holders(
                push_holder_ids
            ):
                tokens_by_holder[push_token.holder_id].append(push_token)

        dead_token_ids: set[uuid.UUID] = set()
        for delivery, notification in due:
            if delivery.channel == DeliveryChannel.SOCKET.value:
                await self._deliver_socket(delivery, notification)
            else:
                await self._deliver_push(
                    delivery,
                    notification,
                    tokens_by_holder.get(delivery.holder_id, []),
                    dead_token_ids,
                )
        await self.push_tokens.deactivate_tokens(dead_token_ids)
        await self.session.commit()
        return len(due)

    async def _deliver_socket(
        self, delivery: NotificationDelivery, notification: InboxNotification
    ) -> None:
        if self.socket_publisher is None:
            self._finish(delivery, DeliveryStatus.SKIPPED, "socket disabled")
            return
        try:
            await self.socket_publisher.publish(
                delivery.holder_id, to_wallet_payload(notification)
            )
        except Exception as exc:
            # Whatever the Redis client raised, the row is retried later;
            # one bad publish must not stop the rest of the batch.
            self._schedule_retry(delivery, type(exc).__name__)
            return
        self._finish(delivery, DeliveryStatus.DELIVERED)

    async def _deliver_push(
        self,
        delivery: NotificationDelivery,
        notification: InboxNotification,
        push_tokens: list[PushToken],
        dead_token_ids: set[uuid.UUID],
    ) -> None:
        if self.push_sender is None:
            self._finish(delivery, DeliveryStatus.SKIPPED, "push disabled")
            return
        if not push_tokens:
            self._finish(delivery, DeliveryStatus.SKIPPED, "no active device")
            return
        payload = to_wallet_payload(notification)
        message = PushMessage(
            title=notification.title,
            body=notification.message,
            data=to_push_data(payload),
        )
        is_delivered, should_retry, last_error = False, False, None
        for push_token in push_tokens:
            result = await self.push_sender.send(push_token.token, message)
            is_delivered = is_delivered or result.delivered
            should_retry = should_retry or result.is_retryable
            if result.is_token_dead:
                dead_token_ids.add(push_token.id)
            last_error = result.error or last_error
        if is_delivered:
            self._finish(delivery, DeliveryStatus.DELIVERED)
        elif should_retry:
            self._schedule_retry(delivery, last_error or "push failed")
        else:
            self._finish(delivery, DeliveryStatus.FAILED, last_error)

    def _schedule_retry(
        self, delivery: NotificationDelivery, error: str
    ) -> None:
        delivery.attempts += 1
        delivery.last_error = error[:_MAX_ERROR_LENGTH]
        if delivery.attempts >= self.settings.notification_max_attempts:
            delivery.status = DeliveryStatus.FAILED.value
            logger.warning(
                "Delivery %s gave up after %s attempts",
                delivery.id,
                delivery.attempts,
            )
            return
        backoff_index = min(delivery.attempts, len(RETRY_BACKOFF_SECONDS)) - 1
        delivery.next_attempt_at = utc_now() + timedelta(
            seconds=RETRY_BACKOFF_SECONDS[backoff_index]
        )

    @staticmethod
    def _finish(
        delivery: NotificationDelivery,
        status: DeliveryStatus,
        note: str | None = None,
    ) -> None:
        delivery.attempts += 1
        delivery.status = status.value
        delivery.last_error = note[:_MAX_ERROR_LENGTH] if note else None
