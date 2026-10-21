"""HTTP routes for holder registration, sign-in, and passwords."""

from fastapi import APIRouter, status

from app.features.auth.dependencies import AuthServiceDep, CurrentAuth
from app.features.auth.schemas import (
    AcceptedResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    OtpSendRequest,
    OtpVerifyRequest,
    RegisterRequest,
    RegistrationTokenResponse,
    ResetPasswordRequest,
    TokenResponse,
)
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/auth", tags=["Auth"])

_UNAUTHORIZED = {status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}}


@router.post(
    "/otp/send",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a registration code",
    responses={status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse}},
)
async def send_registration_otp(
    payload: OtpSendRequest, service: AuthServiceDep
) -> AcceptedResponse:
    """Send a 6-digit code to the email, at most once per cooldown."""
    await service.send_registration_otp(payload.email)
    return AcceptedResponse(message="If the address is valid, a code is sent.")


@router.post(
    "/otp/verify",
    response_model=RegistrationTokenResponse,
    summary="Verify a registration code",
    responses={status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
)
async def verify_registration_otp(
    payload: OtpVerifyRequest, service: AuthServiceDep
) -> RegistrationTokenResponse:
    """Exchange a valid code for a short-lived registration token."""
    return await service.verify_registration_otp(payload.email, payload.code)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a holder",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def register_holder(
    payload: RegisterRequest, service: AuthServiceDep
) -> TokenResponse:
    """Create the account and DID, and sign the holder in."""
    return await service.register(payload)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in with email or DID",
    responses=_UNAUTHORIZED,
)
async def login_holder(
    payload: LoginRequest, service: AuthServiceDep
) -> TokenResponse:
    """Open a session; repeated failures lock the account for a while."""
    return await service.login(payload.identifier, payload.password)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out of this device",
    responses=_UNAUTHORIZED,
)
async def logout_holder(auth: CurrentAuth, service: AuthServiceDep) -> None:
    """End the current session and stop pushes to this device."""
    await service.logout(auth.holder, auth.session)


@router.post(
    "/password/change",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change password",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    auth: CurrentAuth,
    service: AuthServiceDep,
) -> None:
    """Replace the password; every other session is signed out."""
    await service.change_password(
        auth.holder,
        auth.session,
        payload.current_password,
        payload.new_password,
    )


@router.post(
    "/password/forgot",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a password reset link",
)
async def request_password_reset(
    payload: ForgotPasswordRequest, service: AuthServiceDep
) -> AcceptedResponse:
    """Send a reset link if the email has an account."""
    await service.request_password_reset(payload.email)
    return AcceptedResponse(
        message="If the address has an account, a reset link is sent."
    )


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reset password with a reset token",
    responses={status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
)
async def reset_password(
    payload: ResetPasswordRequest, service: AuthServiceDep
) -> None:
    """Set a new password and sign out every session."""
    await service.reset_password(payload.token, payload.new_password)
