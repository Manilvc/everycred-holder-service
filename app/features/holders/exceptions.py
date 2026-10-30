"""Errors raised by the holders feature."""

from app.core.exceptions import UnprocessableError


class UnsupportedImageError(UnprocessableError):
    """Raised when a profile image is not PNG, JPEG, or WebP base64."""

    error_code = "unsupported_image"
