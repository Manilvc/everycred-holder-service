import json
from typing import Any

import httpx
from httpx import AsyncClient

from app.core.config import get_settings
from tests.conftest import FakeConnector, RecordingMailer, RegisteredHolder


def normalized_credential(**overrides: Any) -> dict[str, Any]:
    credential = {
        "credential_id": "cred-1",
        "source_code": "dcs-india",
        "status": "issued",
        "title": "B.Tech Degree",
        "holder_name": "Test Holder",
        "issuer": {"name": "Example University", "did": "did:evrc:issuer:1"},
        "issued_at": "2026-01-01T00:00:00Z",
        "fields": {"grade": "A"},
        "credential_url": "https://dcs.example.com/credential/cred-1",
        "image_url": None,
        "qr_code_url": "https://dcs.example.com/qr/cred-1.png",
        "hash": "abc",
        "credential_json": {"@context": [], "id": "urn:uuid:cred-1"},
    }
    credential.update(overrides)
    return credential


def respond_with(payload: Any, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return handler


async def test_list_credentials_asks_connector_for_the_holder(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    connector.handlers["/v1/holders/credentials/lookup"] = respond_with(
        {
            "items": [
                {
                    "source_code": "dcs-india",
                    "credential_id": "cred-1",
                    "status": "issued",
                    "credential": normalized_credential(),
                    "error": None,
                }
            ]
        }
    )

    response = await client.get("/v1/credentials", headers=holder.headers)

    assert response.status_code == 200
    assert (
        response.json()["items"][0]["credential"]["title"] == "B.Tech Degree"
    )
    request = connector.requests[-1]
    assert connector.last_body() == {"holder_email": holder.email}
    assert request.headers["X-API-Key"] == (
        get_settings().connector_api_key.get_secret_value()
    )


async def test_credential_of_someone_else_is_not_found(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    connector.handlers["/v1/holders/credentials/get"] = respond_with(
        {"error": {"code": "credential_not_found", "message": "Not found."}},
        status_code=404,
    )

    response = await client.get(
        "/v1/credentials/cred-9", headers=holder.headers
    )

    assert response.status_code == 404
    assert connector.last_body() == {
        "holder_email": holder.email,
        "credential_id": "cred-9",
    }


async def test_connector_outage_is_reported_as_bad_gateway(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    connector.handlers["/v1/holders/credentials/lookup"] = respond_with(
        {"error": {"code": "internal_error", "message": "boom"}},
        status_code=500,
    )

    response = await client.get("/v1/credentials", headers=holder.headers)

    assert response.status_code == 502


async def test_download_returns_the_credential_document(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    connector.handlers["/v1/holders/credentials/get"] = respond_with(
        normalized_credential()
    )

    response = await client.get(
        "/v1/credentials/cred-1/download", headers=holder.headers
    )

    assert response.status_code == 200
    assert response.json() == {"@context": [], "id": "urn:uuid:cred-1"}
    assert "attachment" in response.headers["content-disposition"]


async def test_share_requires_a_public_link(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    connector.handlers["/v1/holders/credentials/get"] = respond_with(
        normalized_credential(credential_url=None)
    )

    response = await client.get(
        "/v1/credentials/cred-1/share", headers=holder.headers
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "credential_not_shareable"


async def test_email_credential_is_rate_limited(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
    mailer: RecordingMailer,
) -> None:
    connector.handlers["/v1/holders/credentials/get"] = respond_with(
        normalized_credential()
    )
    payload = {"recipient_email": "verifier@example.com"}
    url = "/v1/credentials/cred-1/email"

    statuses = [
        (
            await client.post(url, json=payload, headers=holder.headers)
        ).status_code
        for _ in range(get_settings().credential_email_hourly_limit + 1)
    ]

    assert statuses[:-1] == [202] * (len(statuses) - 1)
    assert statuses[-1] == 429
    assert mailer.sent[-1].recipient == "verifier@example.com"
    assert "https://dcs.example.com/credential/cred-1" in mailer.sent[-1].body


async def test_verification_stats_are_forwarded_to_the_source(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    connector.handlers["/v1/holders/operations"] = respond_with(
        {
            "items": [
                {
                    "source_code": "dcs-india",
                    "status_code": 200,
                    "ok": True,
                    "data": {"verifications": 3},
                    "message": None,
                }
            ]
        }
    )

    response = await client.get(
        "/v1/sources/dcs-india/credentials/cred-1/stats",
        headers=holder.headers,
    )

    assert response.json()["items"][0]["data"] == {"verifications": 3}
    assert json.loads(connector.requests[-1].content) == {
        "holder_email": holder.email,
        "operation": "credentials.stats",
        "source_code": "dcs-india",
        "params": {"credential_id": "cred-1"},
        "body": None,
    }
