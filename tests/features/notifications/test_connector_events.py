import time

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.signatures import DELIVERY_HEADER, SIGNATURE_HEADER
from app.features.notifications.models import NotificationDelivery
from tests.conftest import RegisteredHolder
from tests.features.notifications.helpers import credential_event, post_event


async def test_signed_event_creates_inbox_entry_and_deliveries(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await post_event(client, credential_event(holder.email))

    inbox = await client.get("/v1/notifications", headers=holder.headers)
    async with session_factory() as session:
        deliveries = (
            await session.scalars(select(NotificationDelivery))
        ).all()
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    item = inbox.json()["items"][0]
    assert item["notification_type"] == "credential_issued"
    assert item["redirect_path"] == "everycredwallet://credential/cred-123"
    assert item["extra_metadata"] == {
        "source_code": "dcs-india",
        "credential_id": "cred-123",
    }
    assert sorted(d.channel for d in deliveries) == ["push", "socket"]


async def test_repeated_delivery_is_acknowledged_once(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    payload = credential_event(holder.email)

    first = await post_event(client, payload, delivery_id="delivery-1")
    second = await post_event(client, payload, delivery_id="delivery-1")

    inbox = await client.get("/v1/notifications", headers=holder.headers)
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"
    assert inbox.json()["total"] == 1


async def test_event_for_unknown_holder_is_ignored(
    client: AsyncClient,
) -> None:
    response = await post_event(
        client, credential_event("not-registered@example.com")
    )

    assert response.status_code == 202
    assert response.json() == {"status": "ignored"}


async def test_wrong_secret_is_rejected(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await post_event(
        client, credential_event(holder.email), secret="x" * 40
    )

    assert response.status_code == 401
    assert response.json()["message"] == "The signature is invalid."


async def test_stale_signature_is_rejected(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await post_event(
        client,
        credential_event(holder.email),
        timestamp=int(time.time()) - 3600,
    )

    assert response.status_code == 401


async def test_missing_signature_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/connector/events",
        content=b"{}",
        headers={DELIVERY_HEADER: "delivery-1"},
    )

    assert response.status_code == 401


async def test_tampered_body_is_rejected(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    signed = await post_event(client, credential_event(holder.email))
    assert signed.status_code == 202

    response = await client.post(
        "/v1/connector/events",
        content=b'{"tampered": true}',
        headers={
            DELIVERY_HEADER: "delivery-2",
            SIGNATURE_HEADER: f"t={int(time.time())},v1={'0' * 64}",
        },
    )

    assert response.status_code == 401


async def test_signed_but_invalid_body_is_rejected(
    client: AsyncClient,
) -> None:
    payload = credential_event("holder@example.com", event="unknown.event")

    response = await post_event(client, payload)

    assert response.status_code == 400
    assert response.json()["message"] == "The event body is invalid."


async def test_request_declined_event_maps_to_declined_notification(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    payload = credential_event(holder.email, event="request.updated")
    payload["data"].update(
        credential_id=None, request_id="req-9", status="declined"
    )

    await post_event(client, payload)

    inbox = await client.get("/v1/notifications", headers=holder.headers)
    item = inbox.json()["items"][0]
    assert item["notification_type"] == "credential_request_declined"
    assert item["redirect_module"] == "requests"
    assert item["redirect_path"] == "everycredwallet://request/req-9"


async def test_mark_notification_read(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    await post_event(client, credential_event(holder.email))
    inbox = await client.get("/v1/notifications", headers=holder.headers)
    notification_id = inbox.json()["items"][0]["id"]

    response = await client.post(
        f"/v1/notifications/{notification_id}/read", headers=holder.headers
    )
    unread = await client.get(
        "/v1/notifications",
        params={"unread_only": True},
        headers=holder.headers,
    )

    assert response.json()["is_read"] is True
    assert unread.json()["total"] == 0


async def test_holder_cannot_read_another_holders_notification(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        "/v1/notifications/00000000-0000-0000-0000-000000000000/read",
        headers=holder.headers,
    )

    assert response.status_code == 404
