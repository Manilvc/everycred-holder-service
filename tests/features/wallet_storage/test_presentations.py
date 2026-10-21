import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from tests.conftest import MemoryStorage, RegisteredHolder

PRESENTATION = b'{"@context": ["https://www.w3.org/ns/credentials/v2"]}'


async def upload(
    client: AsyncClient, holder: RegisteredHolder, content: bytes
):
    return await client.post(
        "/v1/holders/me/storage",
        files={"file": ("vp.json", content, "application/json")},
        headers=holder.headers,
    )


async def test_presentation_is_stored_under_the_holder_prefix(
    client: AsyncClient, holder: RegisteredHolder, storage: MemoryStorage
) -> None:
    response = await upload(client, holder, PRESENTATION)

    body = response.json()
    key = (
        f"holders/{holder.holder_id}/presentations/"
        f"{body['presentation_id']}.json"
    )
    assert response.status_code == 201
    assert storage.objects[key] == (PRESENTATION, "application/json")
    assert body["url_expires_in_seconds"] == (
        get_settings().storage_url_ttl_seconds
    )


@pytest.mark.parametrize("content", [b"not json", b"[1, 2, 3]", b"\xff\xfe"])
async def test_non_object_json_is_rejected(
    client: AsyncClient, holder: RegisteredHolder, content: bytes
) -> None:
    response = await upload(client, holder, content)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_presentation"


async def test_oversized_presentation_is_rejected(
    client: AsyncClient,
    holder: RegisteredHolder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "max_presentation_bytes", 16)

    response = await upload(client, holder, PRESENTATION)

    assert response.status_code == 413
