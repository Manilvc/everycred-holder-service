import base64
import json

from httpx import AsyncClient

from tests.conftest import MemoryStorage, RegisteredHolder

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

DCS_PROFILE_KEYS = {
    "id",
    "uuid",
    "digi_client_id",
    "name",
    "email",
    "profile_image",
    "login_type",
    "did",
    "qrcode_path",
    "holder_profile_path",
    "is_kyc",
    "is_terms_accepted",
    "status",
    "created_at",
    "updated_at",
    "deleted_at",
    "contact",
}


async def test_get_holder_has_the_dcs_shape(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get("/v1/holder", headers=holder.headers)

    body = response.json()
    data = body["data"]
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["message"] == "Holder retrieved successfully!"
    assert set(data) == DCS_PROFILE_KEYS
    assert isinstance(data["id"], int)
    assert 0 < data["id"] < 2**53
    assert data["did"].startswith("did:evrc:holder:")
    assert data["login_type"] == "register"
    assert data["status"] == "registered"
    assert data["profile_image"] is None
    # Naive ISO-8601, as the DCS returns.
    assert "+" not in data["created_at"]


async def test_update_profile_returns_phone_number_and_image_url(
    client: AsyncClient, holder: RegisteredHolder, storage: MemoryStorage
) -> None:
    response = await client.put(
        "/v1/holder/update",
        json={
            "name": "Renamed Holder",
            "contact": "+9876543210",
            "profile_image": base64.b64encode(PNG_BYTES).decode(),
        },
        headers=holder.headers,
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert response.json()["message"] == (
        "Your handler profile is updated successfully."
    )
    assert data["name"] == "Renamed Holder"
    assert data["phone_number"] == "+9876543210"
    assert "contact" not in data
    assert data["profile_image"].startswith("https://")
    profile_document = json.loads(
        storage.objects[
            next(
                key for key in storage.objects if key.endswith("profile.json")
            )
        ][0]
    )
    assert profile_document["name"] == "Renamed Holder"
    assert profile_document["image"].startswith("data:image/png;base64,")
    assert "+9876543210" not in json.dumps(profile_document)


async def test_update_rejects_unsupported_image(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.put(
        "/v1/holder/update",
        json={"profile_image": base64.b64encode(b"GIF89a....").decode()},
        headers=holder.headers,
    )

    assert response.status_code == 422
    assert response.json()["status"] == "fail"
    assert response.json()["message"].startswith("Image format not supported")


async def test_update_rejects_unknown_fields(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.put(
        "/v1/holder/update",
        json={"email": "new@example.com"},
        headers=holder.headers,
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "email"
