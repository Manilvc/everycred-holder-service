import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
from google.oauth2 import service_account
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.features.devices.models import PushToken
from app.features.notifications.channels import (
    FcmPushSender,
    PushMessage,
    PushResult,
    RedisSocketPublisher,
    to_push_data,
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
    registered = await client.put(
        "/v1/push/holder/token",
        json={"token": FCM_TOKEN, "platform": "ios"},
        headers=holder.headers,
    )
    assert registered.status_code == 200, registered.text
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
    assert str(holder_id) == holder.uuid
    assert payload["notification_type"] == "credential_issued"
    token, message = push.sent[0]
    assert token == FCM_TOKEN
    # Same data as the DCS push: metadata at the top level, no nesting.
    assert message.data["type"] == "credential_issued"
    assert message.data["category"] == "credential"
    assert message.data["credential_id"] == "cred-123"
    assert message.data["source_code"] == "dcs-india"
    assert "extra_metadata" not in message.data
    assert "title" not in message.data
    assert all(isinstance(value, str) for value in message.data.values())


async def test_request_push_carries_the_request_id_like_the_dcs(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registered = await client.put(
        "/v1/push/holder/token",
        json={"token": FCM_TOKEN, "platform": "android"},
        headers=holder.headers,
    )
    assert registered.status_code == 200, registered.text
    event = credential_event(holder.email, event="request.created")
    event["data"].update(credential_id=None, request_id="req-9", status=None)
    await post_event(client, event)
    push = FakePushSender(PushResult(delivered=True))

    await deliver(session_factory, None, push)

    _, message = push.sent[0]
    assert message.title == "New credential request"
    assert message.data["type"] == "new_credential_request"
    assert message.data["category"] == "issuer"
    assert message.data["request_id"] == "req-9"
    assert message.data["redirect_entity_id"] == "req-9"


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


def test_push_data_drops_reserved_keys_and_empty_values() -> None:
    data = to_push_data(
        {
            "uuid": "n-1",
            "notification_type": "credential_issued",
            "redirect_path": None,
            "extra_metadata": {
                "credential_id": "cred-1",
                "from": "spoof",
                "google.c.a": "x",
                "items": [1, 2],
                "count": 2,
                "uuid": "metadata-loses",
            },
        }
    )

    assert data == {
        "uuid": "n-1",
        "notification_type": "credential_issued",
        "credential_id": "cred-1",
        "count": "2",
        "type": "credential_issued",
        "category": "credential",
    }


async def test_fcm_message_uses_the_android_channel() -> None:
    sent: list[dict[str, Any]] = []

    def fcm(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"name": "projects/p/messages/1"})

    with patch.object(
        service_account.Credentials, "from_service_account_info"
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(fcm)
        ) as http_client:
            sender = FcmPushSender(http_client, "p", {}, "default")
            with patch.object(
                sender, "_access_token", AsyncMock(return_value="t")
            ):
                result = await sender.send(
                    FCM_TOKEN, PushMessage(title="T", body="B", data={})
                )

    assert result.delivered
    android = sent[0]["message"]["android"]
    assert android == {
        "priority": "high",
        "notification": {"channel_id": "default"},
    }
    assert sent[0]["message"]["notification"] == {"title": "T", "body": "B"}
