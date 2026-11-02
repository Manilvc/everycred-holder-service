"""Live delivery channels: socket events through Redis, and FCM pushes.

Socket events are not sent directly. They are published to the Redis
channel the EveryCRED Socket service subscribes to, with the same JSON
shape DCS publishes::

    {"event": "new_request", "data": {...}, "user_uuid": "<holder id>",
     "room": "user_<holder id>"}

The Socket service emits ``data`` to ``room``; the wallet joins the
room of its holder id after signing in.

Pushes use the FCM HTTP v1 API with a Google service account. The
OAuth token is refreshed with google-auth (blocking, so in a thread) and
cached until it expires; messages are sent with the shared httpx client.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import redis.asyncio as redis
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.features.notifications.messages import push_category

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_SEND_URL = (
    "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
)
# Push ``data`` keys copied from the inbox payload, as the DCS sends them
# (push_notification_service.build_inbox_push_message).
PUSH_DATA_KEYS = (
    "uuid",
    "notification_type",
    "redirect_module",
    "redirect_path",
    "redirect_entity_type",
    "redirect_entity_id",
)
# FCM rejects the whole message for these data keys and key prefixes.
FCM_RESERVED_DATA_KEYS = frozenset({"from", "notification", "message_type"})
FCM_RESERVED_DATA_KEY_PREFIXES = ("google", "gcm")
# FCM error codes meaning the token will never work again.
_DEAD_TOKEN_ERRORS = frozenset({"UNREGISTERED", "SENDER_ID_MISMATCH"})
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class SocketPublisher(Protocol):
    """Publishes a live event for one holder."""

    async def publish(
        self, holder_id: uuid.UUID, payload: dict[str, Any]
    ) -> None:
        """Send ``payload`` to the holder's socket room."""


@dataclass(frozen=True, slots=True)
class PushResult:
    """Outcome of sending one push to one token."""

    delivered: bool
    is_token_dead: bool = False
    is_retryable: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PushMessage:
    """Title, body and data of a push notification."""

    title: str
    body: str
    data: dict[str, str]


class PushSender(Protocol):
    """Sends a push notification to one device token."""

    async def send(self, token: str, message: PushMessage) -> PushResult:
        """Send ``message`` to ``token``; never raises for FCM errors."""


class RedisSocketPublisher:
    """Publishes socket events to the Socket service's Redis channel.

    Attributes:
        client: Redis client for the Socket service's database.
        channel: Channel the Socket service subscribes to.
        event: Socket.IO event name the wallet listens for.
    """

    def __init__(self, client: redis.Redis, channel: str, event: str) -> None:
        self.client = client
        self.channel = channel
        self.event = event

    async def publish(
        self, holder_id: uuid.UUID, payload: dict[str, Any]
    ) -> None:
        """Publish ``payload`` to room ``user_<holder_id>``."""
        message = {
            "event": self.event,
            "data": payload,
            "user_uuid": str(holder_id),
            "room": f"user_{holder_id}",
        }
        await self.client.publish(self.channel, json.dumps(message))


class FcmPushSender:
    """Sends pushes through the FCM HTTP v1 API.

    Attributes:
        http_client: Shared outbound HTTP client.
        project_id: Firebase project id.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        project_id: str,
        service_account_info: dict[str, Any],
        android_channel_id: str,
    ) -> None:
        self.http_client = http_client
        self.project_id = project_id
        self.android_channel_id = android_channel_id
        self._credentials = (
            service_account.Credentials.from_service_account_info(
                service_account_info, scopes=[FCM_SCOPE]
            )
        )

    async def send(self, token: str, message: PushMessage) -> PushResult:
        """Send one push; map FCM errors to a :class:`PushResult`."""
        access_token = await self._access_token()
        body = {
            "message": {
                "token": token,
                "notification": {"title": message.title, "body": message.body},
                "data": message.data,
                "android": {
                    "priority": "high",
                    "notification": {"channel_id": self.android_channel_id},
                },
                "apns": {
                    "headers": {
                        "apns-priority": "10",
                        "apns-push-type": "alert",
                    },
                    "payload": {"aps": {"sound": "default"}},
                },
            }
        }
        try:
            response = await self.http_client.post(
                FCM_SEND_URL.format(project_id=self.project_id),
                json=body,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as exc:
            return PushResult(
                delivered=False, is_retryable=True, error=type(exc).__name__
            )
        if response.is_success:
            return PushResult(delivered=True)
        return self._parse_error(response)

    async def _access_token(self) -> str:
        if not self._credentials.valid:
            await run_in_threadpool(
                self._credentials.refresh, GoogleAuthRequest()
            )
        return str(self._credentials.token)

    @staticmethod
    def _parse_error(response: httpx.Response) -> PushResult:
        error_code = None
        try:
            error = response.json().get("error") or {}
            error_code = error.get("status")
            for detail in error.get("details") or []:
                if isinstance(detail, dict) and detail.get("errorCode"):
                    error_code = detail["errorCode"]
                    break
        except (ValueError, AttributeError):
            pass
        is_token_dead = error_code in _DEAD_TOKEN_ERRORS or (
            response.status_code == httpx.codes.NOT_FOUND
        )
        return PushResult(
            delivered=False,
            is_token_dead=is_token_dead,
            is_retryable=not is_token_dead
            and response.status_code in _RETRYABLE_STATUSES,
            error=f"FCM HTTP {response.status_code} {error_code or '-'}",
        )


def create_socket_publisher(settings: Settings) -> SocketPublisher | None:
    """Return a publisher, or None when ``SOCKET_REDIS_URL`` is unset."""
    if settings.socket_redis_url is None:
        return None
    client = redis.from_url(settings.socket_redis_url.get_secret_value())
    return RedisSocketPublisher(
        client, settings.socket_channel, settings.socket_event
    )


def create_push_sender(
    settings: Settings, http_client: httpx.AsyncClient
) -> PushSender | None:
    """Return an FCM sender, or None when FCM is not configured."""
    if not settings.fcm_project_id:
        return None
    info = settings.fcm_service_account_info()
    return FcmPushSender(
        http_client,
        settings.fcm_project_id,
        info,
        settings.fcm_android_channel_id,
    )


def to_push_data(payload: dict[str, Any]) -> dict[str, str]:
    """Return the FCM ``data`` for a wallet payload, as the DCS sends it.

    The wallet app opens a push from these keys, so they match the DCS
    push exactly: the inbox fields in ``PUSH_DATA_KEYS``, every scalar
    value of ``extra_metadata`` at the top level (``request_id``,
    ``credential_id``, ``source_code``), ``type`` (the notification type)
    and ``category``. FCM-reserved keys and ``None`` values are dropped,
    and every value is a string, as FCM requires.
    """
    data: dict[str, Any] = {}
    metadata = payload.get("extra_metadata")
    if isinstance(metadata, dict):
        data.update(
            (str(key), value)
            for key, value in metadata.items()
            if isinstance(value, str | int | float | bool)
            and not _is_reserved_data_key(str(key))
        )
    # Inbox fields win over metadata keys of the same name.
    data.update((key, payload.get(key)) for key in PUSH_DATA_KEYS)
    notification_type = str(
        payload.get("notification_type") or "inbox_notification"
    )
    data["type"] = notification_type
    data["category"] = push_category(notification_type)
    return {
        key: value if isinstance(value, str) else str(value)
        for key, value in data.items()
        if value is not None
    }


def _is_reserved_data_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in FCM_RESERVED_DATA_KEYS or lowered.startswith(
        FCM_RESERVED_DATA_KEY_PREFIXES
    )
