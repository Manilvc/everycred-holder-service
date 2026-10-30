from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.features.devices.models import PushToken
from tests.conftest import RecordingMailer, RegisteredHolder, register_holder

FCM_TOKEN = "fcm-token-" + "a" * 40
URL = "/v1/push/holder/token"


async def test_register_push_token(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await client.put(
        URL,
        json={
            "token": FCM_TOKEN,
            "platform": "android",
            "device_label": "Pixel 8",
            "app_version": "2.3.0",
        },
        headers=holder.headers,
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Device registered for notifications."
    assert response.json()["data"]["platform"] == "android"
    async with session_factory() as session:
        row = await session.scalar(select(PushToken))
    assert row is not None
    assert row.is_active
    assert row.device_label == "Pixel 8"


async def test_unregister_push_token(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    await client.put(
        URL,
        json={"token": FCM_TOKEN, "platform": "ios"},
        headers=holder.headers,
    )

    response = await client.request(
        "DELETE", URL, json={"token": FCM_TOKEN}, headers=holder.headers
    )

    assert response.status_code == 200
    assert response.json()["message"] == (
        "Device unregistered from notifications."
    )


async def test_cannot_unregister_another_holders_token(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    other = await register_holder(client, mailer, "other@example.com")
    await client.put(
        URL,
        json={"token": FCM_TOKEN, "platform": "ios"},
        headers=other.headers,
    )

    response = await client.request(
        "DELETE", URL, json={"token": FCM_TOKEN}, headers=holder.headers
    )

    assert response.status_code == 404
    assert response.json()["message"] == (
        "This device isn't registered for notifications."
    )


async def test_account_deletion_deactivates_push_tokens(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await client.put(
        URL,
        json={"token": FCM_TOKEN, "platform": "android"},
        headers=holder.headers,
    )

    await client.delete("/v1/holder", headers=holder.headers)

    async with session_factory() as session:
        row = await session.scalar(select(PushToken))
    assert row is not None
    assert not row.is_active
