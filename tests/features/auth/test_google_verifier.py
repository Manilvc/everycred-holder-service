import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from google.auth import crypt
from google.auth import jwt as google_jwt

from app.core.exceptions import ExternalServiceError
from app.features.auth.google import (
    GOOGLE_CERTS_URL,
    GoogleIdTokenVerifier,
    InvalidGoogleTokenError,
)

CLIENT_ID = "wallet-client.apps.googleusercontent.com"
KEY_ID = "test-key"


@pytest.fixture(scope="module")
def signing_key() -> tuple[str, str]:
    """Return a private key PEM and its self-signed certificate PEM."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    return private_pem, cert_pem


def _token(private_pem: str, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234",
        "email": "Holder@Example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
        **overrides,
    }
    signer = crypt.RSASigner.from_string(private_pem, key_id=KEY_ID)
    return google_jwt.encode(signer, claims).decode()


def _verifier(cert_pem: str, status_code: int = 200) -> GoogleIdTokenVerifier:
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == GOOGLE_CERTS_URL
        return httpx.Response(status_code, json={KEY_ID: cert_pem})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return GoogleIdTokenVerifier(client, [CLIENT_ID])


async def test_valid_token_gives_lower_cased_email(
    signing_key: tuple[str, str],
) -> None:
    private_pem, cert_pem = signing_key

    identity = await _verifier(cert_pem).verify(_token(private_pem))

    assert identity.email == "holder@example.com"
    assert identity.subject == "1234"


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"iss": "https://evil.example.com"},
        {"email_verified": False},
        {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
    ],
)
async def test_unacceptable_tokens_are_rejected(
    signing_key: tuple[str, str], overrides: dict[str, Any]
) -> None:
    private_pem, cert_pem = signing_key

    with pytest.raises(InvalidGoogleTokenError):
        await _verifier(cert_pem).verify(_token(private_pem, **overrides))


async def test_token_signed_by_another_key_is_rejected(
    signing_key: tuple[str, str],
) -> None:
    _, cert_pem = signing_key
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    with pytest.raises(InvalidGoogleTokenError):
        await _verifier(cert_pem).verify(_token(other_pem))


async def test_unavailable_certificates_are_a_service_error(
    signing_key: tuple[str, str],
) -> None:
    private_pem, cert_pem = signing_key

    with pytest.raises(ExternalServiceError):
        await _verifier(cert_pem, status_code=503).verify(_token(private_pem))
