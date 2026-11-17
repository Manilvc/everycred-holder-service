import base64
import json
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from app.core.connector import NormalizedCredential
from app.features.credentials.linked import (
    chain_id_of,
    document_id_of,
    document_of,
    normalize_credential_id,
    previous_ids_of,
)
from tests.conftest import (
    FakeConnector,
    RecordingMailer,
    RegisteredHolder,
    register_holder,
)

LINKED_URL = "/v1/holder/credential/linked"
LIST_URL = "/v1/user/holder/credentials"
ROOT = "11111111-1111-1111-1111-111111111111"
SECOND = "22222222-2222-2222-2222-222222222222"
OTHER_ROOT = "44444444-4444-4444-4444-444444444444"
STANDALONE = "55555555-5555-5555-5555-555555555555"
LIST_LINK = "https://cdn.example.com/linked/root.json"


def _document(
    document_id: str, chain_id: str | None, previous_id: str | None = None
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "type": ["VerifiableCredential"],
        "id": f"urn:uuid:{document_id}",
    }
    if chain_id is not None:
        document["linkedCredentialData"] = {
            "ownerUUID": None,
            "previousOwnershipCredentialId": None,
            "previousCredentialsId": (
                {f"urn:uuid:{previous_id}": LIST_LINK} if previous_id else None
            ),
            "firstCredentialLinkedList": {f"urn:uuid:{chain_id}": LIST_LINK},
        }
    return document


def _item(
    credential_id: str,
    document: dict[str, Any],
    *,
    first_seen: str,
    subject_name: str,
    status: str = "issued",
) -> dict[str, Any]:
    return {
        "source_code": "dcs-india",
        "credential_id": credential_id,
        "status": status,
        "credential": {
            "credential_id": credential_id,
            "source_code": "dcs-india",
            "status": status,
            "issuer": {"name": "Example Employer"},
            "issued_at": first_seen,
            "subject_name": subject_name,
            "valid_until": None,
            "credential_json_content": json.dumps(document),
        },
        "error": None,
        "first_seen_at": first_seen,
        "status_changed_at": "2026-11-12T08:00:00+00:00",
    }


@pytest.fixture
def chain(connector: FakeConnector) -> None:
    connector.handlers["/v1/holders/credentials/lookup"] = lambda request: (
        httpx.Response(
            200,
            json={
                "items": [
                    _item(
                        "letter",
                        _document(SECOND, ROOT, previous_id=ROOT),
                        first_seen="2026-11-10T09:00:00+00:00",
                        subject_name="Experience Letter",
                        status="revoked",
                    ),
                    _item(
                        "employment",
                        _document(ROOT, ROOT),
                        first_seen="2026-11-05T10:00:00+00:00",
                        subject_name="Employment Verification",
                    ),
                    _item(
                        "elsewhere",
                        _document(OTHER_ROOT, OTHER_ROOT),
                        first_seen="2026-11-01T10:00:00+00:00",
                        subject_name="Another Chain",
                    ),
                    _item(
                        "degree",
                        _document(STANDALONE, None),
                        first_seen="2026-10-01T10:00:00+00:00",
                        subject_name="B.Tech",
                    ),
                ]
            },
        )
    )


async def _ids_by_uuid(
    client: AsyncClient, holder: RegisteredHolder
) -> dict[str, int]:
    rows = []
    for bucket in ("issued", "revoked"):
        response = await client.get(
            LIST_URL,
            params={
                "holder_id": holder.holder_id,
                "type": bucket,
                "page": 1,
                "per_page": 0,
            },
            headers=holder.headers,
        )
        rows.extend(response.json()["data"])
    return {row["uuid"]: row["id"] for row in rows}


@pytest.mark.usefixtures("chain")
async def test_linked_lists_the_chain_oldest_first_with_names_and_status(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    ids = await _ids_by_uuid(client, holder)

    response = await client.get(
        LINKED_URL, params={"cred_id": ids["letter"]}, headers=holder.headers
    )

    body = response.json()
    assert response.status_code == 200
    assert body["message"] == "Linked credentials fetched successfully!"
    assert body["data"]["chain_id"] == ROOT
    assert body["data"]["credentials"] == [
        {
            "id": ids["employment"],
            "credential_id": ROOT,
            "previous_credential_ids": [],
            "subject_name": "Employment Verification",
            "issuer_name": "Example Employer",
            "issued_at": "2026-11-05T10:00:00",
            "revoked": False,
            "revoked_at": None,
            "valid_until": None,
            "is_current": False,
        },
        {
            "id": ids["letter"],
            "credential_id": SECOND,
            "previous_credential_ids": [ROOT],
            "subject_name": "Experience Letter",
            "issuer_name": "Example Employer",
            "issued_at": "2026-11-10T09:00:00",
            "revoked": True,
            "revoked_at": "2026-11-12T08:00:00",
            "valid_until": None,
            "is_current": True,
        },
    ]


@pytest.mark.usefixtures("chain")
async def test_linked_is_null_for_a_standalone_credential(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    ids = await _ids_by_uuid(client, holder)

    response = await client.get(
        LINKED_URL, params={"cred_id": ids["degree"]}, headers=holder.headers
    )

    assert response.status_code == 200
    assert response.json()["data"] is None
    assert response.json()["message"] == "Credential is not linked."


@pytest.mark.usefixtures("chain")
async def test_linked_rejects_another_holders_id(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    ids = await _ids_by_uuid(client, holder)
    other = await register_holder(client, mailer, "other@example.com")

    response = await client.get(
        LINKED_URL, params={"cred_id": ids["letter"]}, headers=other.headers
    )

    assert response.status_code == 404


def _sd_jwt_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = (
        base64.urlsafe_b64encode(json.dumps(payload).encode())
        .rstrip(b"=")
        .decode()
    )
    return {
        "format": "vc+ld+sd_jwt",
        "credential": f"eyJhbGciOiJFZERTQSJ9.{encoded}.signature",
        "disclosures": [],
    }


def test_chain_and_document_ids_are_read_from_an_sd_jwt_payload() -> None:
    envelope = _sd_jwt_envelope(_document(SECOND, ROOT))

    assert chain_id_of(envelope) == ROOT
    assert document_id_of(envelope) == SECOND


@pytest.mark.parametrize(
    "block",
    [
        "linked",
        {"firstCredentialLinkedList": {}},
        {"firstCredentialLinkedList": {"a": LIST_LINK, "b": LIST_LINK}},
    ],
)
def test_a_damaged_block_reads_as_standalone(block: object) -> None:
    assert chain_id_of({"id": ROOT, "linkedCredentialData": block}) is None


def test_previous_ids_join_both_maps_without_duplicates() -> None:
    document = _document(SECOND, ROOT, previous_id=ROOT)
    document["linkedCredentialData"]["previousOwnershipCredentialId"] = {
        f"urn:uuid:{OTHER_ROOT.upper()}": LIST_LINK,
        f"urn:uuid:{ROOT}": LIST_LINK,
    }

    assert previous_ids_of(document) == [ROOT, OTHER_ROOT]
    assert previous_ids_of(_document(STANDALONE, None)) == []


def test_ids_compare_without_prefix_or_case() -> None:
    assert normalize_credential_id(f"URN:UUID:{ROOT.upper()}") == ROOT
    assert normalize_credential_id("urn:uuid:") is None
    assert normalize_credential_id(7) is None


def test_document_of_falls_back_to_the_parsed_document() -> None:
    credential = NormalizedCredential(
        credential_id="x",
        source_code="dcs-india",
        status="issued",
        credential_json={"id": ROOT},
        credential_json_content="not json",
    )

    assert document_of(credential) == {"id": ROOT}
