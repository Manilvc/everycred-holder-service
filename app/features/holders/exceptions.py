"""Errors raised by the holders feature."""

from fastapi import status

from app.core.exceptions import AppError


class UnsupportedImageError(AppError):
    """Raised when a profile image is not PNG, JPEG, or WebP."""

    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    error_code = "unsupported_image"
