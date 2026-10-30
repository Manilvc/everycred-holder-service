"""Holder account routes, at the DCS paths the wallet app calls.

Paths, bodies, status codes and messages match the DCS backend, so the
app only has to point ``EXPO_PUBLIC_API_BASE_URL`` at this service. See
``docs/wallet_compatibility.md`` for the full contract.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Form, Path, Query, status
from fastapi.responses import JSONResponse

from app.core.responses import respond
from app.features.auth.dependencies import AuthServiceDep, CurrentAuth
from app.features.auth.schemas import (
    ChangePasswordRequest,
    EmailConfirmationRequest,
    ForgotPasswordRequest,
    LoginRequest,
    OtpLoginRequest,
    RecoverRequest,
    RegisterRequest,
    SendOtpRequest,
    SsoLoginRequest,
    SsoType,
    ValidateHolderRequest,
    VerifyOtpRequest,
)
from app.features.holders.dependencies import HolderProfileServiceDep
from app.shared.schemas import DcsResponse, ErrorResponse

router = APIRouter(tags=["Holder Account"])

_ERRORS = {
    status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
}
_FORGOT_MESSAGE = (
    "If an account exists for this email, a password reset link has been "
    "sent to it."
)

AnyResponse = DcsResponse[dict[str, Any]]


@router.post(
    "/holder/validate",
    response_model=AnyResponse,
    summary="Check that a holder exists",
    responses=_ERRORS,
)
async def validate_holder(
    payload: ValidateHolderRequest, service: AuthServiceDep
) -> JSONResponse:
    """Answer 200 if an active holder has the email or DID, else 400."""
    await service.validate_holder(payload.email, payload.did)
    return respond(status.HTTP_200_OK, "Holder validated successfully!")


@router.post(
    "/holder/login",
    response_model=AnyResponse,
    summary="Sign in with email or DID",
    responses={
        **_ERRORS,
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
async def login_holder(
    payload: LoginRequest, service: AuthServiceDep
) -> JSONResponse:
    """Return a session token, or a recovery token for a deleted account.

    ``data`` is ``{user_type, token, is_deleted: false}`` normally, or
    ``{is_deleted: true, token}`` when the account was deleted within
    the grace period; that token is only accepted by ``/holder/recover``.
    """
    result = await service.login(payload)
    return respond(status.HTTP_200_OK, result.message, result.data)


@router.post(
    "/holder/login/otp",
    response_model=AnyResponse,
    summary="Sign in after registering, with the OTP login token",
    responses=_ERRORS,
)
async def login_holder_with_otp_token(
    payload: OtpLoginRequest, service: AuthServiceDep
) -> JSONResponse:
    """Exchange the ``login_token`` from ``otp/verify`` for a session.

    Works once, after ``/holder/register`` has used that verification;
    ``data`` is the same as ``/holder/login``.
    """
    result = await service.login_with_otp_token(payload)
    return respond(status.HTTP_200_OK, result.message, result.data)


@router.post(
    "/holder/login/sso",
    response_model=AnyResponse,
    summary="Sign in with Google",
    responses={
        **_ERRORS,
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)
async def sso_login_holder(
    token: Annotated[str, Query(min_length=1, max_length=4096)],
    sso_type: Annotated[SsoType, Query()],
    payload: SsoLoginRequest,
    service: AuthServiceDep,
) -> JSONResponse:
    """Open a session for the account whose email the ID token proves.

    Only ``sso_type=gmail`` is accepted, and only for an existing
    account; the body is accepted for DCS compatibility and ignored.
    """
    result = await service.sso_login(sso_type, token)
    return respond(status.HTTP_200_OK, result.message, result.data)


@router.post(
    "/holder/logout",
    response_model=AnyResponse,
    summary="Sign out of this device",
    responses=_ERRORS,
)
async def logout_holder(
    auth: CurrentAuth, service: AuthServiceDep
) -> JSONResponse:
    """End this session; the token stops working and pushes stop."""
    await service.logout(auth.holder, auth.session)
    return respond(
        status.HTTP_200_OK, "You have been logged out successfully."
    )


@router.post(
    "/holder/email/confirmation",
    response_model=AnyResponse,
    summary="Email a verification link",
)
async def send_email_confirmation(
    payload: EmailConfirmationRequest, service: AuthServiceDep
) -> JSONResponse:
    """Always answer 200, so the endpoint reveals no accounts."""
    await service.send_email_confirmation(payload.email)
    return respond(status.HTTP_200_OK, "Email sent successfully!")


@router.put(
    "/holder/email/verify",
    response_model=AnyResponse,
    summary="Verify an email from its link",
    responses=_ERRORS,
)
async def verify_email(
    verify_token: Annotated[str, Query(min_length=1, max_length=4096)],
    service: AuthServiceDep,
) -> JSONResponse:
    """Accept the token from a verification email."""
    await service.verify_email(verify_token)
    return respond(
        status.HTTP_200_OK,
        "Email verified successfully!",
        {"holder_email_status": "verified"},
    )


@router.post(
    "/holder/recover",
    response_model=AnyResponse,
    summary="Recover a recently deleted account",
    responses=_ERRORS,
)
async def recover_holder(
    payload: RecoverRequest, service: AuthServiceDep
) -> JSONResponse:
    """Restore the account named by the recovery token and sign in."""
    result = await service.recover(payload.recovery_token)
    return respond(status.HTTP_200_OK, result.message, result.data)


@router.post(
    "/holder/register",
    response_model=AnyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a holder",
    responses=_ERRORS,
)
async def register_holder(
    payload: RegisterRequest, service: AuthServiceDep
) -> JSONResponse:
    """Create the account and DID; the email must be OTP-verified first."""
    await service.register(payload)
    return respond(status.HTTP_201_CREATED, "Holder created successfully!")


@router.post(
    "/wallet/holder/otp/send",
    response_model=AnyResponse,
    summary="Email a registration OTP",
    responses={
        **_ERRORS,
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
async def send_otp(
    payload: SendOtpRequest,
    service: AuthServiceDep,
    function: Annotated[
        str | None,
        Query(
            max_length=50,
            description="Accepted for DCS compatibility; ignored.",
        ),
    ] = None,
) -> JSONResponse:
    """Send a 6-digit code to the email, at most once per cooldown."""
    result = await service.send_otp(payload)
    return respond(status.HTTP_200_OK, result.message, result.data)


@router.post(
    "/wallet/holder/otp/verify",
    response_model=AnyResponse,
    summary="Verify a registration OTP",
    responses=_ERRORS,
)
async def verify_otp(
    payload: VerifyOtpRequest, service: AuthServiceDep
) -> JSONResponse:
    """Check the code; errors carry the remaining attempts in ``data``."""
    result = await service.verify_otp(payload)
    return respond(status.HTTP_200_OK, result.message, result.data)


@router.post(
    "/holder/forget",
    response_model=AnyResponse,
    summary="Email a password reset link",
)
async def forgot_password(
    payload: ForgotPasswordRequest, service: AuthServiceDep
) -> JSONResponse:
    """Always answer 200, so the endpoint reveals no accounts."""
    await service.request_password_reset(payload.email)
    return respond(status.HTTP_200_OK, _FORGOT_MESSAGE)


@router.post(
    "/holder/reset/{token}/submit",
    response_model=AnyResponse,
    summary="Set a new password from a reset link",
    responses=_ERRORS,
)
async def submit_password_reset(
    token: Annotated[str, Path(min_length=16, max_length=128)],
    new_password: Annotated[str, Form(min_length=8, max_length=128)],
    confirm_password: Annotated[str, Form(min_length=8, max_length=128)],
    service: AuthServiceDep,
) -> JSONResponse:
    """Used by the web reset page; errors carry ``data.state``."""
    await service.reset_password(token, new_password, confirm_password)
    return respond(status.HTTP_200_OK, "Password reset successfully")


@router.post(
    "/holder/password/change",
    response_model=AnyResponse,
    summary="Change password",
    responses=_ERRORS,
)
async def change_password(
    payload: ChangePasswordRequest,
    auth: CurrentAuth,
    service: AuthServiceDep,
    profiles: HolderProfileServiceDep,
) -> JSONResponse:
    """Replace the password; every other session is signed out."""
    await service.change_password(
        auth.holder,
        auth.session,
        payload.current_password,
        payload.new_password,
        payload.confirm_password,
    )
    detail = await profiles.build_detail(
        auth.holder, contact_key="phone_number"
    )
    return respond(status.HTTP_200_OK, "Password changed successfully", detail)


@router.delete(
    "/holder",
    response_model=AnyResponse,
    summary="Delete my account",
    responses=_ERRORS,
)
async def delete_holder(
    auth: CurrentAuth, service: AuthServiceDep
) -> JSONResponse:
    """Soft-delete the account; sign-in during the grace period recovers it."""
    await service.delete_account(auth.holder)
    return respond(status.HTTP_200_OK, "Holder deleted successfully!")
