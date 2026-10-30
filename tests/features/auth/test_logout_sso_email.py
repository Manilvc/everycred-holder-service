import re

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.features.auth.dependencies import get_google_id_token_verifier
from app.features.auth.google import GoogleIdentity, InvalidGoogleTokenError
from tests.conftest import RecordingMailer, RegisteredHolder, login

SSO_URL = "/v1/holder/login/sso"
SSO_BODY = {"email": "attacker-chosen@example.com"}


class FakeGoogleVerifier:
    """Accepts the token "good-<email>" for that email."""

    is_configured = True

    async def verify(self, id_token: str) -> GoogleIdentity:
        if not id_token.startswith("good-"):
            raise InvalidGoogleTokenError("bad token")
        return GoogleIdentity(subject="google-sub", email=id_token[5:])


@pytest.fixture
def google(app: FastAPI) -> None:
    app.dependency_overrides[get_google_id_token_verifier] = FakeGoogleVerifier


async def test_logout_ends_only_this_session(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    other_token = await login(client, holder.email)

    response = await client.post("/v1/holder/logout", headers=holder.headers)

    assert response.status_code == 200
    assert response.json()["message"] == (
        "You have been logged out successfully."
    )
    assert (
        await client.get("/v1/holder", headers=holder.headers)
    ).status_code == 401
    other = await client.get(
        "/v1/holder", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert other.status_code == 200


async def test_logout_needs_a_token(client: AsyncClient) -> None:
    response = await client.post("/v1/holder/logout")

    assert response.status_code == 401


@pytest.mark.usefixtures("google")
async def test_google_sign_in_uses_the_token_email_not_the_body(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        SSO_URL,
        params={"token": f"good-{holder.email}", "sso_type": "gmail"},
        json=SSO_BODY,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["role_type"] == "holder"
    profile = await client.get(
        "/v1/holder", headers={"Authorization": f"Bearer {data['token']}"}
    )
    assert profile.json()["data"]["email"] == holder.email


@pytest.mark.usefixtures("google", "holder")
async def test_google_sign_in_for_unknown_email_asks_to_register(
    client: AsyncClient,
) -> None:
    response = await client.post(
        SSO_URL,
        params={"token": "good-stranger@example.com", "sso_type": "gmail"},
        json={},
    )

    assert response.status_code == 404
    assert response.json()["message"] == "Please register!"


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("token", "sso_type"),
    [("forged", "gmail"), ("good-holder@example.com", "office365")],
)
async def test_invalid_or_unverifiable_sso_is_rejected(
    client: AsyncClient, holder: RegisteredHolder, token: str, sso_type: str
) -> None:
    response = await client.post(
        SSO_URL, params={"token": token, "sso_type": sso_type}, json=SSO_BODY
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid token"


async def test_sso_without_google_client_ids_is_rejected(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        SSO_URL,
        params={"token": f"good-{holder.email}", "sso_type": "gmail"},
        json={},
    )

    assert response.status_code == 400


async def test_email_confirmation_link_verifies(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    mailer.sent.clear()

    response = await client.post(
        "/v1/holder/email/confirmation", json={"email": holder.email}
    )

    assert response.status_code == 200
    assert response.json()["data"] is None
    token = re.search(r"token=(\S+)", mailer.sent[-1].body).group(1)
    verify = await client.put(
        "/v1/holder/email/verify", params={"verify_token": token}
    )
    assert verify.status_code == 200
    assert verify.json()["data"] == {"holder_email_status": "verified"}


async def test_email_confirmation_reveals_no_accounts(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    response = await client.post(
        "/v1/holder/email/confirmation", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 200
    assert mailer.sent == []


async def test_email_verify_rejects_other_tokens_without_401(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    # An access token is signed with the same key but is not a
    # verification token.
    response = await client.put(
        "/v1/holder/email/verify",
        params={"verify_token": holder.access_token},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid token"
