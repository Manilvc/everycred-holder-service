import json
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from tests.conftest import (
    FakeConnector,
    RecordingMailer,
    RegisteredHolder,
    register_holder,
)

LIST_URL = "/v1/user/holder/credentials"
RAW_DOCUMENT = '{"type": ["VerifiableCredential"], "id": "urn:uuid:u-1"}'


def _credential(credential_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "credential_id": credential_id,
        "source_code": "dcs-india",
        "status": "issued",
        "title": "B.Tech",
        "holder_name": "Test Holder",
        "issuer": {
            "name": "Example University",
            "did": "did:evrc:issuer:x",
            "email": "issuer@example.com",
            "logo_url": "https://cdn.example.com/issuer.png",
            "description": None,
        },
        "issued_at": "2026-10-01T00:00:00Z",
        "fields": {"grade": "A"},
        "credential_url": f"https://cdn.example.com/{credential_id}.json",
        "image_url": f"https://cdn.example.com/{credential_id}.png",
        "qr_code_url": f"https://cdn.example.com/{credential_id}-qr.png",
        "hash": "abc",
        "credential_json": {"type": ["VerifiableCredential"]},
        "credential_unique_id": f"unique-{credential_id}",
        "subject_name": "Computer Science",
        "subject_logo_url": "https://cdn.example.com/subject.png",
        "valid_from": "2026-10-01T00:00:00Z",
        "valid_until": None,
        "credential_json_content": RAW_DOCUMENT,
        **overrides,
    }


def _item(
    credential_id: str, *, first_seen: str, **overrides: Any
) -> dict[str, Any]:
    status = overrides.get("status", "issued")
    return {
        "source_code": "dcs-india",
        "credential_id": credential_id,
        "status": status,
        "credential": _credential(credential_id, **overrides),
        "error": None,
        "first_seen_at": first_seen,
        "status_changed_at": "2026-10-15T08:00:00+00:00",
    }


def _lookup(*items: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"items": list(items)})


@pytest.fixture
def three_credentials(connector: FakeConnector) -> None:
    connector.handlers["/v1/holders/credentials/lookup"] = lambda request: (
        _lookup(
            _item("old", first_seen="2026-09-01T00:00:00+00:00"),
            _item("new", first_seen="2026-10-01T00:00:00+00:00"),
            _item(
                "gone",
                first_seen="2026-08-01T00:00:00+00:00",
                status="revoked",
            ),
            _item(
                "lapsed",
                first_seen="2026-07-01T00:00:00+00:00",
                valid_until="2020-01-01T00:00:00Z",
            ),
            {
                "source_code": "dcs-edu",
                "credential_id": "broken",
                "status": "issued",
                "credential": None,
                "error": "Source dcs-edu could not be reached.",
            },
        )
    )


async def _list(
    client: AsyncClient,
    holder: RegisteredHolder,
    credential_type: str = "issued",
    **params: int,
) -> httpx.Response:
    return await client.get(
        LIST_URL,
        params={
            "holder_id": holder.holder_id,
            "type": credential_type,
            "page": 1,
            "per_page": 8,
            **params,
        },
        headers=holder.headers,
    )


@pytest.mark.usefixtures("three_credentials")
async def test_issued_bucket_has_dcs_rows_newest_first(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await _list(client, holder)

    body = response.json()
    rows = body["data"]["data"]
    assert response.status_code == 200
    assert body["message"] == "Credentials are fetched successfully"
    assert body["data"]["total"] == 2
    assert body["data"]["pages"] == 1
    assert [row["uuid"] for row in rows] == ["new", "old"]
    row = rows[0]
    assert isinstance(row["id"], int)
    assert row["credential_path"] == "https://cdn.example.com/new.json"
    assert row["credential_unique_id"] == "unique-new"
    assert row["subject_name"] == "Computer Science"
    assert row["issuer_name"] == "Example University"
    assert row["logo"] == "https://cdn.example.com/subject.png"
    assert row["issuer_logo"] == "https://cdn.example.com/issuer.png"
    assert row["revoked"] is False
    assert row["revoked_at"] is None
    assert row["is_issued"] is True
    assert row["candidate_name"] == "Test Holder"


@pytest.mark.usefixtures("three_credentials")
async def test_revoked_and_expired_buckets(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    revoked = await _list(client, holder, "revoked")
    expired = await _list(client, holder, "expired")

    [revoked_row] = revoked.json()["data"]["data"]
    [expired_row] = expired.json()["data"]["data"]
    assert revoked_row["uuid"] == "gone"
    assert revoked_row["revoked"] is True
    assert revoked_row["revoked_at"] == "2026-10-15T08:00:00"
    assert expired_row["uuid"] == "lapsed"


@pytest.mark.usefixtures("three_credentials")
async def test_ids_are_stable_between_calls(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    first = await _list(client, holder)
    second = await _list(client, holder)

    assert [row["id"] for row in first.json()["data"]["data"]] == [
        row["id"] for row in second.json()["data"]["data"]
    ]


async def test_empty_bucket_is_404_with_total_zero(
    client: AsyncClient, holder: RegisteredHolder, connector: FakeConnector
) -> None:
    connector.handlers["/v1/holders/credentials/lookup"] = lambda request: (
        _lookup()
    )

    response = await _list(client, holder, page=2)

    assert response.status_code == 404
    assert response.json() == {
        "status": "fail",
        "data": {"data": [], "pages": 2, "total": 0},
        "message": "Details not found!",
    }


async def test_other_holders_id_is_forbidden(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get(
        LIST_URL,
        params={"holder_id": holder.holder_id + 1, "type": "issued"},
        headers=holder.headers,
    )

    assert response.status_code == 403
    assert response.json()["message"] == (
        "You can only view your own credentials."
    )


@pytest.mark.usefixtures("three_credentials")
async def test_per_page_zero_returns_a_plain_list(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await _list(client, holder, page=0, per_page=0)

    assert isinstance(response.json()["data"], list)


@pytest.mark.usefixtures("three_credentials")
async def test_share_uses_the_list_id(
    client: AsyncClient, holder: RegisteredHolder, connector: FakeConnector
) -> None:
    connector.handlers["/v1/holders/credentials/get"] = lambda request: (
        httpx.Response(
            200,
            json=_credential(json.loads(request.content)["credential_id"]),
        )
    )
    rows = (await _list(client, holder)).json()["data"]["data"]

    response = await client.get(
        "/v1/holder/credential/share",
        params={"cred_id": rows[0]["id"]},
        headers=holder.headers,
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert response.json()["message"] == "Credentials share successfully!"
    assert connector.last_body()["credential_id"] == "new"
    assert data["qr_image"] == "https://cdn.example.com/new-qr.png"
    assert data["viewer_link"] == "https://verifier.example.com/unique-new"
    assert data["is_verifiable"] is True
    assert data["logo_image"] == "https://cdn.example.com/subject.png"
    assert data["subject_name"] == "Computer Science"


@pytest.mark.usefixtures("three_credentials")
async def test_another_holder_cannot_use_my_credential_id(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    rows = (await _list(client, holder)).json()["data"]["data"]
    other = await register_holder(client, mailer, "other@example.com")

    response = await client.get(
        "/v1/holder/credential/share",
        params={"cred_id": rows[0]["id"]},
        headers=other.headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "Details not found!"


@pytest.mark.usefixtures("three_credentials")
async def test_stats_pass_through_the_source_answer(
    client: AsyncClient, holder: RegisteredHolder, connector: FakeConnector
) -> None:
    analytics = {"analytics_data": [], "credential_verified": 3, "total": 0}
    connector.handlers["/v1/holders/operations"] = lambda request: (
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "source_code": "dcs-india",
                        "status_code": 200,
                        "ok": True,
                        "data": analytics,
                        "message": "Information retrieved successfully!",
                    }
                ]
            },
        )
    )
    rows = (await _list(client, holder)).json()["data"]["data"]

    response = await client.get(
        "/v1/holder/stats",
        params={"cred_id": rows[0]["id"], "page": 1, "per_page": 5},
        headers=holder.headers,
    )

    sent = connector.last_body()
    assert response.status_code == 200
    assert response.json()["data"] == analytics
    assert sent["operation"] == "credentials.stats"
    assert sent["source_code"] == "dcs-india"
    assert sent["params"] == {"credential_id": "new"}


async def test_stats_for_unknown_id_is_404(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get(
        "/v1/holder/stats",
        params={"cred_id": 12345, "page": 1, "per_page": 5},
        headers=holder.headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "Details not found!"


@pytest.mark.usefixtures("three_credentials")
async def test_notifications_have_dcs_and_app_keys(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get(
        "/v1/holder/credential/notification",
        params={"page": 1, "per_page": 10},
        headers=holder.headers,
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert response.json()["message"] == "Notification received successfully!"
    # Four credentials issued, one of them also revoked.
    assert data["total"] == 5
    revoked = next(item for item in data["data"] if item["type"] == "revoked")
    assert revoked["revoked_at"] == "2026-10-15T08:00:00"
    assert revoked["created_at"] == revoked["revoked_at"]
    assert revoked["credential"] == "Computer Science"
    assert revoked["issuer_name"] == "Example University"
    assert revoked["credential_image"] == "https://cdn.example.com/gone.png"
    created = [item["created_at"] for item in data["data"]]
    assert created == sorted(created, reverse=True)


async def test_no_notifications_is_200(
    client: AsyncClient, holder: RegisteredHolder, connector: FakeConnector
) -> None:
    connector.handlers["/v1/holders/credentials/lookup"] = lambda request: (
        _lookup()
    )

    response = await client.get(
        "/v1/holder/credential/notification", headers=holder.headers
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"data": [], "pages": 1, "total": 0}


async def test_public_lookup_needs_no_token(
    client: AsyncClient, connector: FakeConnector
) -> None:
    connector.handlers["/v1/credentials/unique-1"] = lambda request: (
        httpx.Response(200, json=_credential("unique-1", status="revoked"))
    )

    response = await client.get("/v1/user/credential/unique-1")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["message"] == "Verification completed successfully!"
    assert body["data"]["not_draft"] is True
    assert body["data"]["bn_credential"] is True
    assert body["data"]["is_revoked"] is True
    assert body["data"]["credential_unique_id"] == "unique-unique-1"
    # The raw document is passed on byte for byte.
    assert body["data"]["credential_json_content"] == RAW_DOCUMENT


async def test_public_lookup_of_unknown_credential(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/user/credential/missing")

    assert response.status_code == 404
    assert response.json()["message"] == (
        "Credential does not found from the given id!"
    )


async def test_verification_analytics_is_forwarded(
    client: AsyncClient, connector: FakeConnector
) -> None:
    connector.handlers["/v1/credentials/unique-1/verification-analytics"] = (
        lambda request: httpx.Response(
            200,
            json={
                "source_code": "dcs-india",
                "status_code": 201,
                "ok": True,
                "data": {"id": 7, "last_verified": "2026-10-22T10:00:00"},
                "message": "Information stored successfully",
            },
        )
    )

    response = await client.post(
        "/v1/credential/verification/analytics",
        params={"uuid": "unique-1"},
        json={"verification_status": True, "stage": "", "reason": None},
        headers={"Authorization": "Bearer ignored"},
    )

    assert response.status_code == 201
    assert response.json()["message"] == "Information stored successfully"
    assert response.json()["data"]["id"] == 7
    assert connector.last_body() == {
        "verification_status": True,
        "stage": "",
        "reason": None,
    }


@pytest.fixture
def credential_lookup(connector: FakeConnector) -> None:
    connector.handlers["/v1/holders/credentials/get"] = lambda request: (
        httpx.Response(
            200,
            json=_credential(
                json.loads(request.content)["credential_id"],
                valid_from="2026-10-01T15:30:00Z",
            ),
        )
    )


async def _first_id(client: AsyncClient, holder: RegisteredHolder) -> int:
    return (await _list(client, holder)).json()["data"]["data"][0]["id"]


@pytest.mark.usefixtures("three_credentials", "credential_lookup")
async def test_preview_lists_fields_in_dcs_shape(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get(
        "/v1/holder/credential/preview",
        params={"cred_id": await _first_id(client, holder)},
        headers=holder.headers,
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert response.json()["message"] == (
        "Credential preview fetched successfully!"
    )
    assert data["credential_data"] == [
        {"fname": "grade", "fvalue": "A", "ftype": "text"}
    ]
    assert data["valid_from"] == "2026-10-01 03:30 pm"
    assert data["revoked"] is False
    assert data["subject_name"] == "Computer Science"


@pytest.mark.usefixtures("three_credentials", "credential_lookup")
async def test_download_returns_the_document_link(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get(
        "/v1/holder/credential/download",
        params={"cred_id": await _first_id(client, holder)},
        headers=holder.headers,
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Credential downloaded successfully!"
    assert response.json()["data"] == {
        "credential": "https://cdn.example.com/new.json"
    }


@pytest.mark.usefixtures("three_credentials", "credential_lookup")
async def test_send_email_mails_each_recipient_once(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    mailer.sent.clear()

    response = await client.post(
        "/v1/holder/send/email",
        params={"cred_id": await _first_id(client, holder)},
        json={
            "holder_email": [
                "friend@example.com",
                "boss@example.com",
                "friend@example.com",
            ]
        },
        headers=holder.headers,
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Email sent successfully!"
    assert sorted(email.recipient for email in mailer.sent) == [
        "boss@example.com",
        "friend@example.com",
    ]
    assert "https://verifier.example.com/unique-new" in mailer.sent[0].body
    assert mailer.sent[0].subject == "Computer Science Is Shared"


@pytest.mark.usefixtures("three_credentials", "credential_lookup")
async def test_send_email_refuses_too_many_recipients(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    mailer.sent.clear()
    recipients = [f"person{index}@example.com" for index in range(11)]

    response = await client.post(
        "/v1/holder/send/email",
        params={"cred_id": await _first_id(client, holder)},
        json={"holder_email": recipients},
        headers=holder.headers,
    )

    assert response.status_code == 400
    assert mailer.sent == []


@pytest.mark.usefixtures("three_credentials")
async def test_credential_actions_reject_another_holders_id(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    cred_id = await _first_id(client, holder)
    other = await register_holder(client, mailer, "other@example.com")

    for path in (
        "/v1/holder/credential/preview",
        "/v1/holder/credential/download",
    ):
        response = await client.get(
            path, params={"cred_id": cred_id}, headers=other.headers
        )
        assert response.status_code == 404, path
