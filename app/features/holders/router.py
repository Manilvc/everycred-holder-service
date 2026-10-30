"""Profile routes, at the DCS paths the wallet app calls."""

from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.responses import respond
from app.features.auth.dependencies import CurrentHolder
from app.features.holders.dependencies import HolderProfileServiceDep
from app.features.holders.schemas import UpdateHolder
from app.shared.schemas import DcsResponse, ErrorResponse

router = APIRouter(tags=["Holder Profile"])


@router.get(
    "/holder",
    response_model=DcsResponse[dict[str, Any]],
    summary="Get my profile",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def get_holder(
    holder: CurrentHolder, service: HolderProfileServiceDep
) -> JSONResponse:
    """Return the profile; ``data.id`` is the holder's integer id."""
    detail = await service.build_detail(holder)
    return respond(
        status.HTTP_200_OK, "Holder retrieved successfully!", detail
    )


@router.put(
    "/holder/update",
    response_model=DcsResponse[dict[str, Any]],
    summary="Update my profile",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
async def update_holder(
    changes: UpdateHolder,
    holder: CurrentHolder,
    service: HolderProfileServiceDep,
) -> JSONResponse:
    """Change the name, contact number or profile image (raw base64)."""
    detail = await service.update_profile(holder, changes)
    return respond(
        status.HTTP_200_OK,
        # The DCS wording, typo included, because the app shows it.
        "Your handler profile is updated successfully.",
        detail,
    )
