"""Errors raised by the auth feature."""

from app.core.exceptions import AppError, AuthenticationError, ConflictError


class InvalidCredentialsError(AuthenticationError):
    """Raised for every failed login, whatever the reason.

    Unknown account, wrong password, locked or inactive account all
    look the same, so the response does not reveal which accounts exist.
    """

    error_code = "invalid_credentials"


class InvalidOtpError(AppError):
    """Raised when an OTP is wrong, expired, used, or out of attempts."""

    error_code = "invalid_otp"


class InvalidCurrentPasswordError(AppError):
    """Raised when a password change gives the wrong current password."""

    error_code = "invalid_current_password"


class InvalidResetTokenError(AppError):
    """Raised when a reset token is unknown, used, or expired."""

    error_code = "invalid_reset_token"


class EmailAlreadyRegisteredError(ConflictError):
    """Raised when registering an email that already has an account."""

    error_code = "email_already_registered"
