import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.exceptions import NotFoundError
from app.shared.pagination import Pagination


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    async def raise_not_found() -> None:
        raise NotFoundError("Verification was not found.")

    async def raise_unexpected_error() -> None:
        raise RuntimeError("database password is hunter2")

    async def list_items(pagination: Pagination) -> dict[str, int]:
        return pagination.model_dump()

    app.add_api_route("/test/not-found", raise_not_found)
    app.add_api_route("/test/crash", raise_unexpected_error)
    app.add_api_route("/test/items", list_items)
    return app


async def test_app_error_uses_dcs_envelope(client: AsyncClient) -> None:
    response = await client.get("/test/not-found")

    assert response.status_code == 404
    assert response.json() == {
        "status": "fail",
        "data": None,
        "message": "Verification was not found.",
    }
    assert response.headers["X-Request-ID"]


async def test_unknown_route_uses_dcs_framework_envelope(
    client: AsyncClient,
) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "status": 404,
        "data": None,
        "message": "Not Found",
    }


async def test_unexpected_error_hides_internal_details(
    client: AsyncClient,
) -> None:
    response = await client.get("/test/crash")

    assert response.status_code == 500
    assert response.json()["status"] == "fail"
    assert "hunter2" not in response.text
    assert "X-Request-ID" in response.headers


async def test_validation_error_does_not_echo_input(
    client: AsyncClient,
) -> None:
    response = await client.get("/test/items", params={"limit": "secret"})

    body = response.json()
    assert response.status_code == 422
    assert body["status"] == 422
    assert body["errors"][0]["field"] == "limit"
    assert body["message"].startswith("limit ")
    assert "secret" not in response.text


async def test_pagination_defaults_are_applied(client: AsyncClient) -> None:
    response = await client.get("/test/items")

    assert response.json() == {"limit": 20, "offset": 0}
