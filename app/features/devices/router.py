"""Push token routes, at the DCS paths."""

from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.responses import respond
from app.features.auth.dependencies import CurrentAuth
from app.features.devices.dependencies import PushTokenServiceDep
from app.features.devices.schemas import (
    RegisterPushTokenRequest,
    UnregisterPushTokenRequest,
)
from app.shared.schemas import DcsResponse, ErrorResponse

router = APIRouter(prefix="/push/holder/token", tags=["Devices"])


@router.put(
    "",
    response_model=DcsResponse[dict[str, Any]],
    summary="Register this device for push notifications",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def register_push_token(
    payload: RegisterPushTokenRequest,
    auth: CurrentAuth,
    service: PushTokenServiceDep,
) -> JSONResponse:
    """Save the FCM token, bound to the current session.

    Ending the session (logout, password change, account deletion)
    deactivates the token, so no call is needed then.
    """
    result = await service.register(auth.holder, auth.session, payload)
    return respond(
        status.HTTP_200_OK, "Device registered for notifications.", result
    )


@router.delete(
    "",
    response_model=DcsResponse[dict[str, Any]],
    summary="Turn off push notifications on this device",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def unregister_push_token(
    payload: UnregisterPushTokenRequest,
    auth: CurrentAuth,
    service: PushTokenServiceDep,
) -> JSONResponse:
    """Deactivate one of the holder's tokens."""
    await service.unregister(auth.holder, payload)
    return respond(
        status.HTTP_200_OK, "Device unregistered from notifications."
    )
