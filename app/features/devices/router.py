"""HTTP routes for the current device's push token."""

from fastapi import APIRouter, status

from app.features.auth.dependencies import CurrentAuth
from app.features.devices.dependencies import PushTokenServiceDep
from app.features.devices.schemas import PushTokenRegister, PushTokenResponse

router = APIRouter(prefix="/holders/me/push-token", tags=["Devices"])


@router.put(
    "",
    response_model=PushTokenResponse,
    summary="Register this device for push notifications",
)
async def register_push_token(
    payload: PushTokenRegister,
    auth: CurrentAuth,
    service: PushTokenServiceDep,
) -> PushTokenResponse:
    """Save the FCM token, bound to the current session."""
    return await service.register(auth.holder, auth.session, payload)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Turn off push notifications on this device",
)
async def unregister_push_token(
    auth: CurrentAuth, service: PushTokenServiceDep
) -> None:
    """Deactivate the tokens registered by the current session."""
    await service.unregister(auth.session)
