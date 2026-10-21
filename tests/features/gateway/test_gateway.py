from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from tests.conftest import FakeConnector, RegisteredHolder

OPERATION_RESULT = {
    "items": [
        {
            "source_code": "dcs-india",
            "status_code": 200,
            "ok": True,
            "data": {"done": True},
            "message": None,
        }
    ]
}


@pytest.fixture(autouse=True)
def operations_endpoint(connector: FakeConnector) -> None:
    connector.handlers["/v1/holders/operations"] = lambda request: (
        httpx.Response(200, json=OPERATION_RESULT)
    )


@pytest.mark.parametrize(
    ("method", "path", "operation", "source_code", "params"),
    [
        ("GET", "/v1/requests", "requests.list", None, {}),
        (
            "GET",
            "/v1/sources/dcs-india/requests/req-1/fields",
            "requests.fields",
            "dcs-india",
            {"request_id": "req-1"},
        ),
        (
            "GET",
            "/v1/sources/dcs-india/kyc-detail",
            "kyc.detail",
            "dcs-india",
            {},
        ),
        ("GET", "/v1/workflow-requests", "workflow.list", None, {}),
        (
            "POST",
            "/v1/sources/dcs-india/workflow-requests/wf-1/nodes/n-2/accept",
            "workflow.node_accept",
            "dcs-india",
            {"request_uuid": "wf-1", "node_key": "n-2"},
        ),
        (
            "POST",
            "/v1/sources/dcs-india/requests/req-1/integrations/"
            "confirm/surepass/aadhaar/start",
            "integrations.start",
            "dcs-india",
            {
                "request_id": "req-1",
                "integration_type": "confirm",
                "tool_code": "surepass",
                "flow": "aadhaar",
            },
        ),
        (
            "GET",
            "/v1/sources/dcs-india/digilocker/complete-flow/client-7",
            "digilocker.complete",
            "dcs-india",
            {"client_id": "client-7"},
        ),
    ],
)
async def test_routes_forward_operation_and_params(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
    method: str,
    path: str,
    operation: str,
    source_code: str | None,
    params: dict[str, str],
) -> None:
    kwargs: dict[str, Any] = {"headers": holder.headers}
    if method == "POST":
        kwargs["json"] = {}

    response = await client.request(method, path, **kwargs)

    assert response.status_code == 200, response.text
    assert response.json() == OPERATION_RESULT
    sent = connector.last_body()
    assert sent["holder_email"] == holder.email
    assert sent["operation"] == operation
    assert sent["source_code"] == source_code
    assert sent["params"] == params


async def test_submission_body_is_passed_unchanged(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    answers = {"fields": {"name": "Test Holder", "year": 2026}}

    await client.post(
        "/v1/sources/dcs-india/requests/req-1/submission",
        json=answers,
        headers=holder.headers,
    )

    assert connector.last_body()["body"] == answers


async def test_unsafe_path_values_are_rejected_before_forwarding(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    response = await client.get(
        "/v1/sources/dcs-india/requests/req%2F..%2Fadmin",
        headers=holder.headers,
    )

    assert response.status_code in (404, 422)
    assert connector.requests == []


async def test_connector_validation_error_code_is_passed_through(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
) -> None:
    connector.handlers["/v1/holders/operations"] = lambda request: (
        httpx.Response(
            400,
            json={
                "error": {
                    "code": "source_required",
                    "message": "A source is required.",
                }
            },
        )
    )

    response = await client.get(
        "/v1/sources/dcs-india/requests/req-1", headers=holder.headers
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "source_required"


async def test_gateway_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/v1/requests")

    assert response.status_code == 401
