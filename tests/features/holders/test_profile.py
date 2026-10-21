import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from tests.conftest import MemoryStorage, RegisteredHolder

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def test_profile_includes_did_file_urls(
    client: AsyncClient, holder: RegisteredHolder, storage: MemoryStorage
) -> None:
    response = await client.get("/v1/holders/me", headers=holder.headers)

    body = response.json()
    assert body["full_name"] == "Test Holder"
    assert body["did_qr_code_url"].startswith("https://files.example.com/")
    assert body["profile_image_url"] is None
    assert any(key.endswith("qr-code.png") for key in storage.objects)


async def test_update_profile_changes_only_given_fields(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.patch(
        "/v1/holders/me",
        json={"mobile": "+919876543210"},
        headers=holder.headers,
    )

    assert response.status_code == 200
    assert response.json()["mobile"] == "+919876543210"
    assert response.json()["full_name"] == "Test Holder"


async def test_update_profile_rejects_unknown_fields(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.patch(
        "/v1/holders/me",
        json={"email": "other@example.com"},
        headers=holder.headers,
    )

    assert response.status_code == 422


async def test_profile_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/v1/holders/me")

    assert response.status_code == 401


async def test_upload_profile_image(
    client: AsyncClient, holder: RegisteredHolder, storage: MemoryStorage
) -> None:
    response = await client.put(
        "/v1/holders/me/profile-image",
        files={"image": ("me.png", PNG_BYTES, "image/png")},
        headers=holder.headers,
    )

    assert response.status_code == 200
    assert response.json()["profile_image_url"] is not None
    key = f"holders/{holder.holder_id}/profile-image.png"
    assert storage.objects[key][1] == "image/png"


async def test_profile_image_type_is_checked_from_content(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.put(
        "/v1/holders/me/profile-image",
        files={"image": ("me.png", b"<svg>not a png</svg>", "image/png")},
        headers=holder.headers,
    )

    assert response.status_code == 415


async def test_profile_image_size_is_limited(
    client: AsyncClient,
    holder: RegisteredHolder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "max_profile_image_bytes", 32)

    response = await client.put(
        "/v1/holders/me/profile-image",
        files={"image": ("me.png", PNG_BYTES, "image/png")},
        headers=holder.headers,
    )

    assert response.status_code == 413
