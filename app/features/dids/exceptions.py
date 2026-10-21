"""Errors raised by the DIDs feature."""

from app.core.exceptions import ConflictError, NotFoundError


class DidNotFoundError(NotFoundError):
    """Raised when no active holder owns the requested DID."""

    error_code = "did_not_found"


class HolderKeyNotFoundError(NotFoundError):
    """Raised when the holder has no active key with the given id."""

    error_code = "key_not_found"


class HolderKeyLimitError(ConflictError):
    """Raised when a holder already has the maximum number of keys."""

    error_code = "key_limit_reached"
