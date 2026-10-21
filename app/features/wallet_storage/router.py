"""HTTP route for storing a verifiable presentation."""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from app.core.config import SettingsDep
from app.features.auth.dependencies import CurrentHolder
from app.features.wallet_storage.dependencies import (
    PresentationStorageServiceDep,
)
from app.features.wallet_storage.schemas import StoredPresentationResponse
from app.shared.schemas import ErrorResponse
from app.shared.uploads import read_limited

router = APIRouter(prefix="/holders/me/storage", tags=["Wallet Storage"])


@router.post(
    "",
    response_model=StoredPresentationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store a verifiable presentation",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
    },
)
async def store_presentation(
    file: Annotated[UploadFile, File(description="Presentation JSON")],
    holder: CurrentHolder,
    service: PresentationStorageServiceDep,
    settings: SettingsDep,
) -> StoredPresentationResponse:
    """Upload a presentation JSON and get a short-lived URL to share."""
    content = await read_limited(file, settings.max_presentation_bytes)
    return await service.store_presentation(holder, content)
