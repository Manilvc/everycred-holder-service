"""Credential request routes at the DCS paths the wallet app calls.

Unlike ``router.py``, these answer in the DCS envelope with the DCS
shapes, not one item per source, so the app works by changing only its
base URL. Requests from every DCS source are merged into one list, and
each item carries the ``source_code`` the ``/sources/...`` routes take.

The paths without ``/holder`` are deprecated in the DCS and kept here
for the same app versions.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.core.responses import respond
from app.features.auth.dependencies import CurrentHolder
from app.features.gateway.dependencies import GatewayServiceDep
from app.features.gateway.schemas import RequestSubmission
from app.shared.identifiers import ExternalId
from app.shared.schemas import DcsResponse, ErrorResponse

wallet_router = APIRouter(
    tags=["Credential Requests"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)

AnyResponse = DcsResponse[Any]
REQUESTS_FETCHED = "Issuer Requests fetched successfully!"
REQUEST_SUBMITTED = "Request submitted successfully!"


@wallet_router.get(
    "/holder/subject/requests",
    response_model=AnyResponse,
    summary="List my credential requests (DCS shape)",
)
async def list_requests(
    holder: CurrentHolder,
    service: GatewayServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 10,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> JSONResponse:
    """Return ``{subjects, total, page, size, pages}``, newest first.

    ``search`` matches subject name, issuer name or request id.
    """
    result = await service.list_requests(holder, page, size, search)
    return respond(status.HTTP_200_OK, REQUESTS_FETCHED, result)


@wallet_router.get(
    "/subject/requests",
    response_model=AnyResponse,
    summary="List my credential requests, unpaged (deprecated)",
    deprecated=True,
)
async def list_requests_legacy(
    holder: CurrentHolder, service: GatewayServiceDep
) -> JSONResponse:
    """Return ``{subjects, total}`` with every request."""
    result = await service.list_requests(holder)
    return respond(status.HTTP_200_OK, REQUESTS_FETCHED, result)


@wallet_router.get(
    "/request/{request_id}",
    response_model=AnyResponse,
    summary="Get a credential request (deprecated path)",
    deprecated=True,
)
@wallet_router.get(
    "/holder/request/{request_id}",
    response_model=AnyResponse,
    summary="Get a credential request (DCS shape)",
)
async def get_request(
    request_id: ExternalId,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> JSONResponse:
    """Return the request and its fields from the DCS that sent it."""
    result = await service.get_request(holder, request_id)
    return respond(
        result.status_code, result.message or REQUESTS_FETCHED, result.data
    )


@wallet_router.post(
    "/request/submission",
    response_model=AnyResponse,
    summary="Submit a credential request (deprecated path)",
    deprecated=True,
)
@wallet_router.post(
    "/holder/request/submission",
    response_model=AnyResponse,
    summary="Submit a credential request (DCS shape)",
)
async def submit_request(
    payload: RequestSubmission,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> JSONResponse:
    """Send the holder's answers to the DCS that sent the request."""
    result = await service.submit_request(
        holder, payload.model_dump(exclude_unset=True)
    )
    return respond(
        result.status_code, result.message or REQUEST_SUBMITTED, result.data
    )
