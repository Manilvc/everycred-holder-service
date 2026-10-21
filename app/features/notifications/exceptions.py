"""Errors raised by the notifications feature."""

from app.core.exceptions import AppError, AuthenticationError, NotFoundError


class InvalidEventSignatureError(AuthenticationError):
    """Raised when a connector webhook's signature is missing or wrong."""

    error_code = "invalid_signature"
    headers = None


class InvalidEventError(AppError):
    """Raised when a signed connector webhook has an unusable body."""

    error_code = "invalid_event"


class NotificationNotFoundError(NotFoundError):
    """Raised when the holder has no notification with the given id."""

    error_code = "notification_not_found"
