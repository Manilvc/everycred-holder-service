"""Presentation storage route, at the DCS path the wallet app calls."""

from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.responses import respond
from app.features.auth.dependencies import CurrentHolder
from app.features.wallet_storage.dependencies import (
    PresentationStorageServiceDep,
)
from app.features.wallet_storage.schemas import HolderStorageRequest
from app.shared.schemas import DcsResponse, ErrorResponse

router = APIRouter(tags=["Wallet Storage"])


@router.post(
    "/holder/storage",
    response_model=DcsResponse[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
    summary="Store a verifiable presentation",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
    },
)
async def store_presentation(
    payload: HolderStorageRequest,
    holder: CurrentHolder,
    service: PresentationStorageServiceDep,
) -> JSONResponse:
    """Upload a presentation and get a URL that works for its window.

    ``data.file_path`` is the URL to put in the QR code;
    ``valid_from``/``valid_until`` are echoed as ``YYYY-MM-DDTHH:MM:SSZ``.
    """
    result = await service.store_presentation(holder, payload)
    return respond(
        status.HTTP_201_CREATED, "Data Uploaded Successfully!", result
    )
