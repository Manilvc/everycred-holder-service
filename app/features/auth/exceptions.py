"""Errors raised by the auth feature.

Messages are the ones the DCS returns, because the wallet app shows
them to the user verbatim. Where the DCS fell back to a generic message
because of a bug, a specific message is used instead.
"""

from fastapi import status

from app.core.exceptions import AppError, NotFoundError

INVALID_LOGIN_MESSAGE = "Email or Password is invalid"
GRACE_EXPIRED_MESSAGE = (
    "This account is no longer recoverable. You can register again with "
    "the same email to get your credential(s) back."
)


class InvalidLoginError(AppError):
    """Raised when the password is wrong or the account cannot sign in."""

    error_code = "invalid_credentials"


class UnknownHolderLoginError(NotFoundError):
    """Raised when no holder has the email or DID (DCS answers 404)."""

    error_code = "invalid_credentials"


class AccountLockedError(AppError):
    """Raised after too many failed sign-ins, until the lock expires."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "account_locked"


class AccountNotRecoverableError(AppError):
    """Raised at login when a deleted account's grace period is over."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "account_not_recoverable"


class InvalidOtpError(AppError):
    """Raised when an OTP is missing, wrong, expired, used, or exhausted."""

    error_code = "invalid_otp"


class InvalidLoginTokenError(AppError):
    """Raised when an OTP login token cannot open a session.

    Answers 400, not 401: the app signs the holder out after a second
    401, and this token says nothing about an existing session.
    """

    error_code = "invalid_login_token"


class RegistrationError(AppError):
    """Raised when a registration request cannot be accepted."""

    error_code = "registration_failed"


class PasswordChangeError(AppError):
    """Raised when a password change or reset is refused."""

    error_code = "password_change_failed"


class InvalidRecoveryError(AppError):
    """Raised when an account recovery request cannot be accepted."""

    error_code = "invalid_recovery"


class SocialLoginError(AppError):
    """Raised when a provider token cannot sign a holder in."""

    error_code = "invalid_social_login"


class InvalidEmailVerificationError(AppError):
    """Raised when an email verification token is unusable.

    Answers 400, not 401: the app signs the holder out after a second
    401, and this token says nothing about the session.
    """

    error_code = "invalid_email_verification"


class InvalidResetLinkError(AppError):
    """Raised when a password reset link is unusable.

    ``data`` carries ``{"state": "expired" | "superseded" | "invalid"}``
    as the DCS does, so the web reset page can explain what happened.
    """

    error_code = "invalid_reset_link"
