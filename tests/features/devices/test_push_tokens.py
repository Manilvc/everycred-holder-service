from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.features.devices.models import PushToken
from tests.conftest import RegisteredHolder

FCM_TOKEN = "fcm-token-" + "a" * 40


async def load_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> PushToken | None:
    async with session_factory() as session:
        return await session.scalar(
            select(PushToken).where(PushToken.token == FCM_TOKEN)
        )


async def register_token(client: AsyncClient, holder: RegisteredHolder):
    return await client.put(
        "/v1/holders/me/push-token",
        json={"token": FCM_TOKEN, "platform": "android"},
        headers=holder.headers,
    )


async def test_register_push_token(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await register_token(client, holder)

    push_token = await load_token(session_factory)
    assert response.status_code == 200
    assert push_token is not None and push_token.is_active
    assert str(push_token.holder_id) == holder.holder_id


async def test_registering_again_does_not_duplicate(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_token(client, holder)
    await register_token(client, holder)

    async with session_factory() as session:
        rows = (await session.scalars(select(PushToken))).all()
    assert len(rows) == 1


async def test_unregister_push_token(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_token(client, holder)

    response = await client.delete(
        "/v1/holders/me/push-token", headers=holder.headers
    )

    push_token = await load_token(session_factory)
    assert response.status_code == 204
    assert push_token is not None and not push_token.is_active


async def test_logout_stops_pushes_to_the_device(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_token(client, holder)

    await client.post("/v1/auth/logout", headers=holder.headers)

    push_token = await load_token(session_factory)
    assert push_token is not None and not push_token.is_active


async def test_malformed_token_is_rejected(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.put(
        "/v1/holders/me/push-token",
        json={"token": "short", "platform": "android"},
        headers=holder.headers,
    )

    assert response.status_code == 422
