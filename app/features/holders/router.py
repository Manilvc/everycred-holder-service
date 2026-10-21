"""HTTP routes for the signed-in holder's profile."""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from app.core.config import SettingsDep
from app.features.auth.dependencies import CurrentHolder
from app.features.holders.dependencies import HolderProfileServiceDep
from app.features.holders.schemas import (
    HolderProfileResponse,
    HolderProfileUpdate,
)
from app.shared.schemas import ErrorResponse
from app.shared.uploads import read_limited

router = APIRouter(prefix="/holders/me", tags=["Holder Profile"])


@router.get(
    "",
    response_model=HolderProfileResponse,
    summary="Get my profile",
)
async def get_my_profile(
    holder: CurrentHolder, service: HolderProfileServiceDep
) -> HolderProfileResponse:
    """Return the profile, including the DID and its QR code URL."""
    return await service.get_profile(holder)


@router.patch(
    "",
    response_model=HolderProfileResponse,
    summary="Update my profile",
)
async def update_my_profile(
    changes: HolderProfileUpdate,
    holder: CurrentHolder,
    service: HolderProfileServiceDep,
) -> HolderProfileResponse:
    """Change the name or mobile number."""
    return await service.update_profile(holder, changes)


@router.put(
    "/profile-image",
    response_model=HolderProfileResponse,
    summary="Replace my profile image",
    responses={
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
    },
)
async def replace_my_profile_image(
    image: Annotated[UploadFile, File(description="PNG, JPEG, or WebP")],
    holder: CurrentHolder,
    service: HolderProfileServiceDep,
    settings: SettingsDep,
) -> HolderProfileResponse:
    """Upload a profile image up to ``MAX_PROFILE_IMAGE_BYTES``."""
    content = await read_limited(image, settings.max_profile_image_bytes)
    return await service.replace_profile_image(holder, content)
