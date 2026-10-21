"""Errors raised by the wallet storage feature."""

from app.core.exceptions import AppError


class InvalidPresentationError(AppError):
    """Raised when an upload is not a JSON object."""

    error_code = "invalid_presentation"
