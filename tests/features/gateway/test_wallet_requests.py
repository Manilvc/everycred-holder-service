import json
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from tests.conftest import FakeConnector, RegisteredHolder


def _result(
    source_code: str, status_code: int, data: Any, message: str | None = None
) -> dict[str, Any]:
    return {
        "source_code": source_code,
        "status_code": status_code,
        "ok": 200 <= status_code < 300,
        "data": data,
        "message": message,
    }


def _subject(request_id: str, created_at: str, **extra: Any) -> dict:
    return {
        "request_id": request_id,
        "created_at": created_at,
        "subject_name": "Degree",
        **extra,
    }


def _operations(connector: FakeConnector) -> list[dict[str, Any]]:
    return [
        json.loads(request.content)
        for request in connector.requests
        if request.url.path == "/v1/holders/operations"
    ]


@pytest.fixture
def two_sources(connector: FakeConnector) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        operation = body["operation"]
        if operation == "requests.list":
            items = [
                _result(
                    "dcs-india",
                    200,
                    {"subjects": [_subject("r-old", "2026-09-01T00:00:00")]},
                ),
                _result(
                    "dcs-edu",
                    200,
                    {
                        "subjects": [
                            _subject(
                                "r-new",
                                "2026-10-01T00:00:00",
                                subject_name="Transcript",
                            )
                        ]
                    },
                ),
                _result("dcs-down", 502, None, "unreachable"),
            ]
        elif operation == "requests.find":
            found = body["params"]["request_id"] == "r-new"
            items = [
                _result("dcs-india", 404, None, "Request not found!"),
                _result(
                    "dcs-edu",
                    200 if found else 404,
                    {"request_id": "r-new"} if found else None,
                    "Issuer Requests fetched successfully!",
                ),
            ]
        else:
            items = [
                _result(
                    body["source_code"],
                    200,
                    None,
                    "Request submitted successfully!",
                )
            ]
        return httpx.Response(200, json={"items": items})

    connector.handlers["/v1/holders/operations"] = handle


@pytest.mark.usefixtures("two_sources")
async def test_list_merges_sources_newest_first(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get(
        "/v1/holder/subject/requests", headers=holder.headers
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert (
        response.json()["message"] == "Issuer Requests fetched successfully!"
    )
    assert [item["request_id"] for item in data["subjects"]] == [
        "r-new",
        "r-old",
    ]
    assert data["subjects"][0]["source_code"] == "dcs-edu"
    assert (data["total"], data["page"], data["size"], data["pages"]) == (
        2,
        1,
        10,
        1,
    )


@pytest.mark.usefixtures("two_sources")
async def test_list_search_and_legacy_unpaged_shape(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    searched = await client.get(
        "/v1/holder/subject/requests",
        params={"search": "transcript"},
        headers=holder.headers,
    )
    legacy = await client.get("/v1/subject/requests", headers=holder.headers)

    assert [s["request_id"] for s in searched.json()["data"]["subjects"]] == [
        "r-new"
    ]
    assert set(legacy.json()["data"]) == {"subjects", "total"}


@pytest.mark.usefixtures("two_sources")
@pytest.mark.parametrize(
    "path", ["/v1/holder/request/r-new", "/v1/request/r-new"]
)
async def test_get_finds_the_request_in_its_source(
    client: AsyncClient, holder: RegisteredHolder, path: str
) -> None:
    response = await client.get(path, headers=holder.headers)

    assert response.status_code == 200
    assert response.json()["data"] == {
        "request_id": "r-new",
        "source_code": "dcs-edu",
    }


@pytest.mark.usefixtures("two_sources")
async def test_get_unknown_request_is_404(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get(
        "/v1/holder/request/r-none", headers=holder.headers
    )

    assert response.status_code == 404


@pytest.mark.usefixtures("two_sources")
async def test_submission_goes_to_the_requests_own_source(
    client: AsyncClient, holder: RegisteredHolder, connector: FakeConnector
) -> None:
    body = {"request_id": "r-new", "slug": '{"name": "Test"}'}

    response = await client.post(
        "/v1/holder/request/submission", json=body, headers=holder.headers
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Request submitted successfully!"
    submit = _operations(connector)[-1]
    assert submit["operation"] == "requests.submit"
    assert submit["source_code"] == "dcs-edu"
    assert submit["params"] == {"request_id": "r-new"}
    assert submit["body"] == body
