import re
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import MemoryStorage, RegisteredHolder

URL = "/v1/holder/storage"
PRESENTATION = {"@context": ["https://www.w3.org/ns/credentials/v2"]}
DCS_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


async def test_store_presentation_with_window(
    client: AsyncClient, holder: RegisteredHolder, storage: MemoryStorage
) -> None:
    now = datetime.now(UTC)
    response = await client.post(
        URL,
        json={
            "data": PRESENTATION,
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(minutes=10)).isoformat(),
        },
        headers=holder.headers,
    )

    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "success"
    assert body["message"] == "Data Uploaded Successfully!"
    assert body["data"]["file_path"].startswith("https://files.example.com/")
    assert DCS_TIME.match(body["data"]["valid_from"])
    assert DCS_TIME.match(body["data"]["valid_until"])
    [(key, ttl)] = storage.url_ttls.items()
    assert key.startswith(f"holders/{holder.uuid}/presentations/")
    assert ttl is not None
    assert 540 <= ttl <= 600


async def test_store_presentation_without_dates_uses_default_window(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        URL, json={"data": PRESENTATION}, headers=holder.headers
    )

    assert response.status_code == 201


async def test_only_valid_from_does_not_crash(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        URL,
        json={
            "data": PRESENTATION,
            "valid_from": datetime.now(UTC).isoformat(),
        },
        headers=holder.headers,
    )

    assert response.status_code == 201


async def test_window_ending_in_the_past_is_rejected(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    response = await client.post(
        URL,
        json={
            "data": PRESENTATION,
            "valid_from": past.isoformat(),
            "valid_until": (past + timedelta(minutes=5)).isoformat(),
        },
        headers=holder.headers,
    )

    assert response.status_code == 400
    assert response.json()["status"] == "fail"


async def test_storage_requires_a_token(client: AsyncClient) -> None:
    response = await client.post(URL, json={"data": PRESENTATION})

    assert response.status_code == 401
