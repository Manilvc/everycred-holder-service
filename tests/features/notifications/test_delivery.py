import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.features.devices.models import PushToken
from app.features.notifications.channels import (
    PushMessage,
    PushResult,
    RedisSocketPublisher,
)
from app.features.notifications.models import NotificationDelivery
from app.features.notifications.service import NotificationDeliveryService
from tests.conftest import RegisteredHolder
from tests.features.notifications.helpers import credential_event, post_event

FCM_TOKEN = "fcm-token-" + "b" * 40


class FakeSocketPublisher:
    def __init__(self, error: Exception | None = None) -> None:
        self.published: list[tuple[uuid.UUID, dict[str, Any]]] = []
        self.error = error

    async def publish(
        self, holder_id: uuid.UUID, payload: dict[str, Any]
    ) -> None:
        if self.error:
            raise self.error
        self.published.append((holder_id, payload))


class FakePushSender:
    def __init__(self, result: PushResult) -> None:
        self.result = result
        self.sent: list[tuple[str, PushMessage]] = []

    async def send(self, token: str, message: PushMessage) -> PushResult:
        self.sent.append((token, message))
        return self.result


class FakeRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


async def deliver(
    session_factory: async_sessionmaker[AsyncSession],
    socket_publisher: FakeSocketPublisher | None,
    push_sender: FakePushSender | None,
) -> dict[str, NotificationDelivery]:
    async with session_factory() as session:
        service = NotificationDeliveryService(
            session, get_settings(), socket_publisher, push_sender
        )
        await service.deliver_due(batch_size=10)
    async with session_factory() as session:
        rows = (await session.scalars(select(NotificationDelivery))).all()
    return {row.channel: row for row in rows}


async def queue_event_with_device(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    await client.put(
        "/v1/holders/me/push-token",
        json={"token": FCM_TOKEN, "platform": "ios"},
        headers=holder.headers,
    )
    await post_event(client, credential_event(holder.email))


async def test_worker_delivers_over_socket_and_push(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_event_with_device(client, holder)
    socket = FakeSocketPublisher()
    push = FakePushSender(PushResult(delivered=True))

    deliveries = await deliver(session_factory, socket, push)

    assert deliveries["socket"].status == "delivered"
    assert deliveries["push"].status == "delivered"
    holder_id, payload = socket.published[0]
    assert str(holder_id) == holder.holder_id
    assert payload["notification_type"] == "credential_issued"
    token, message = push.sent[0]
    assert token == FCM_TOKEN
    assert message.data["type"] == "credential_issued"
    assert all(isinstance(value, str) for value in message.data.values())


async def test_unconfigured_channels_are_skipped(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_event_with_device(client, holder)

    deliveries = await deliver(session_factory, None, None)

    assert deliveries["socket"].status == "skipped"
    assert deliveries["push"].status == "skipped"


async def test_failed_socket_publish_is_retried_later(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_event_with_device(client, holder)
    socket = FakeSocketPublisher(error=ConnectionError("redis down"))

    deliveries = await deliver(session_factory, socket, None)

    socket_delivery = deliveries["socket"]
    assert socket_delivery.status == "pending"
    assert socket_delivery.attempts == 1
    assert socket_delivery.last_error == "ConnectionError"


async def test_dead_push_token_is_deactivated(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_event_with_device(client, holder)
    push = FakePushSender(PushResult(delivered=False, is_token_dead=True))

    deliveries = await deliver(session_factory, None, push)

    async with session_factory() as session:
        push_token = await session.scalar(select(PushToken))
    assert deliveries["push"].status == "failed"
    assert push_token is not None and not push_token.is_active


async def test_redis_publisher_uses_the_dcs_socket_message_shape() -> None:
    redis = FakeRedis()
    publisher = RedisSocketPublisher(
        redis,  # type: ignore[arg-type]
        "socketio_notifications",
        "new_request",
    )
    holder_id = uuid.uuid4()

    await publisher.publish(holder_id, {"title": "New Credential Received"})

    channel, message = redis.messages[0]
    assert channel == "socketio_notifications"
    assert message == (
        '{"event": "new_request", "data": {"title": '
        '"New Credential Received"}, "user_uuid": "'
        f'{holder_id}", "room": "user_{holder_id}"}}'
    )
