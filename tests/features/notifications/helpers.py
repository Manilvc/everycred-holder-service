import time
import uuid
from typing import Any

from httpx import AsyncClient, Response

from app.core.config import get_settings
from app.core.signatures import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    encode_body,
    sign,
)


def credential_event(
    holder_email: str, event: str = "credential.issued"
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "event": event,
        "created_at": "2026-10-21T10:00:00+00:00",
        "data": {
            "source_code": "dcs-india",
            "holder_email": holder_email,
            "credential_id": "cred-123",
            "request_id": None,
            "status": "issued",
        },
    }


async def post_event(
    client: AsyncClient,
    payload: dict[str, Any],
    *,
    delivery_id: str | None = None,
    secret: str | None = None,
    timestamp: int | None = None,
) -> Response:
    body = encode_body(payload)
    signing_secret = (
        secret or get_settings().connector_webhook_secret.get_secret_value()
    )
    signed_at = int(time.time()) if timestamp is None else timestamp
    return await client.post(
        "/v1/connector/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            EVENT_HEADER: payload["event"],
            DELIVERY_HEADER: delivery_id or uuid.uuid4().hex,
            SIGNATURE_HEADER: sign(signing_secret, signed_at, body),
        },
    )
