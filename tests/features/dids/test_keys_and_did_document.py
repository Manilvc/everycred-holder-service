import base64
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient

from app.core.config import get_settings
from tests.conftest import RegisteredHolder


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def ed25519_jwk() -> dict[str, Any]:
    public_key = Ed25519PrivateKey.generate().public_key()
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": b64url(public_key.public_bytes_raw()),
    }


def p256_jwk() -> dict[str, Any]:
    numbers = (
        ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
    )
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64url(numbers.x.to_bytes(32, "big")),
        "y": b64url(numbers.y.to_bytes(32, "big")),
    }


async def register_key(
    client: AsyncClient, holder: RegisteredHolder, jwk: dict[str, Any]
):
    return await client.post(
        "/v1/holders/me/keys",
        json={"public_jwk": jwk},
        headers=holder.headers,
    )


@pytest.mark.parametrize("make_jwk", [ed25519_jwk, p256_jwk])
async def test_registered_key_is_published_in_did_document(
    client: AsyncClient, holder: RegisteredHolder, make_jwk
) -> None:
    jwk = make_jwk()

    created = await register_key(client, holder, jwk)
    document = await client.get(f"/v1/dids/{holder.did}")

    assert created.status_code == 201
    method_id = created.json()["verification_method_id"]
    body = document.json()
    assert document.headers["content-type"] == "application/did+json"
    assert body["id"] == holder.did
    assert body["verificationMethod"][0]["id"] == method_id
    assert body["verificationMethod"][0]["publicKeyJwk"] == jwk
    assert body["assertionMethod"] == [method_id]


async def test_private_key_material_is_rejected(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    jwk = {**ed25519_jwk(), "d": b64url(b"\x01" * 32)}

    response = await register_key(client, holder, jwk)

    assert response.status_code == 422
    assert "private key material" in response.text
    assert jwk["d"] not in response.text


async def test_point_not_on_curve_is_rejected(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    jwk = {**p256_jwk(), "y": b64url(b"\x01" * 32)}

    response = await register_key(client, holder, jwk)

    assert response.status_code == 422


async def test_revoked_key_leaves_did_document(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    created = await register_key(client, holder, ed25519_jwk())
    key_id = created.json()["key_id"]

    revoked = await client.delete(
        f"/v1/holders/me/keys/{key_id}", headers=holder.headers
    )
    document = await client.get(f"/v1/dids/{holder.did}")
    keys = await client.get("/v1/holders/me/keys", headers=holder.headers)

    assert revoked.status_code == 204
    assert document.json()["verificationMethod"] == []
    assert keys.json() == []


async def test_key_limit_is_enforced(
    client: AsyncClient,
    holder: RegisteredHolder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "max_keys_per_holder", 1)
    await register_key(client, holder, ed25519_jwk())

    response = await register_key(client, holder, ed25519_jwk())

    assert response.status_code == 409
    assert response.json()["message"] == (
        "Revoke an existing key before registering another."
    )


async def test_unknown_did_is_not_found(client: AsyncClient) -> None:
    response = await client.get(
        "/v1/dids/did:evrc:holder:00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 404
