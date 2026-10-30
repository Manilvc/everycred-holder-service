"""Domain exceptions and the handlers that turn them into responses.

Services raise subclasses of :class:`AppError` and never deal with HTTP.
The handlers registered by :func:`register_exception_handlers` convert
those errors, request validation failures, and Starlette HTTP errors
into the DCS envelope (see :mod:`app.core.responses`), because the
wallet app shows the ``message`` of every error to the user.

Unexpected exceptions are handled in
:class:`~app.core.middleware.RequestContextMiddleware` instead, so they
are logged while the request id is still available.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.responses import build_envelope, framework_error_body

logger = logging.getLogger(__name__)

# Location parts FastAPI adds that mean nothing to the caller.
_LOCATION_PREFIXES = frozenset({"body", "query", "path", "header", "form"})


class AppError(Exception):
    """Base class for errors that are safe to report to API clients.

    Subclasses set ``status_code`` and ``error_code``. The message is
    returned to the client as-is, so it must not contain secrets,
    personal data, or internal details. ``data`` is returned in the
    envelope's ``data`` field where the DCS contract puts details there,
    such as the remaining OTP attempts.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "bad_request"
    headers: dict[str, str] | None = None

    def __init__(self, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.data = data


class AuthenticationError(AppError):
    """Raised when a token is invalid, expired, or its session ended."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "authentication_failed"
    # RFC 6750 requires 401 responses to name the expected scheme.
    headers = {"WWW-Authenticate": "Bearer"}


class NotAuthenticatedError(AuthenticationError):
    """Raised when a protected route is called without a bearer token.

    The DCS reports this case with the numeric status in the envelope,
    so the handler does the same.
    """

    error_code = "not_authenticated"


class PermissionDeniedError(AppError):
    """Raised when the caller is not allowed to perform the action."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "permission_denied"


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ConflictError(AppError):
    """Raised when the request conflicts with the current state."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class UnprocessableError(AppError):
    """Raised when a well-formed request carries unusable content."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = "unprocessable"


class TooManyRequestsError(AppError):
    """Raised when the caller exceeded a per-holder or per-email limit."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "too_many_requests"


class PayloadTooLargeError(AppError):
    """Raised when an uploaded file is larger than allowed."""

    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    error_code = "payload_too_large"


class ExternalServiceError(AppError):
    """Raised when an upstream service fails or returns bad data."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "external_service_error"


class UpstreamRejectedError(AppError):
    """Raised when the connector rejects a request as invalid.

    The connector's own error code is kept for logging.
    """

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _field_name(location: tuple[Any, ...]) -> str:
    parts = [str(part) for part in location if part not in _LOCATION_PREFIXES]
    return ".".join(parts) or "request"


def _summarise_validation_errors(
    exc: RequestValidationError,
) -> list[dict[str, Any]]:
    # Pydantic includes the rejected input in each error. That input can
    # hold personal data or secrets, so only field, message, and type
    # are echoed back.
    return [
        {
            "field": _field_name(tuple(error["loc"])),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Convert an :class:`AppError` into its error response."""
    logger.info("Request failed with %s: %s", exc.error_code, exc.message)
    if isinstance(exc, NotAuthenticatedError):
        content = framework_error_body(exc.status_code, exc.message)
    else:
        content = build_envelope(exc.status_code, exc.message, exc.data)
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=exc.headers
    )


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Convert a request validation failure into the DCS 422 response."""
    errors = _summarise_validation_errors(exc)
    first = errors[0] if errors else {"field": "request", "message": ""}
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=framework_error_body(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{first['field']} {first['message']}".strip(),
            errors=errors,
        ),
    )


async def handle_http_error(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Convert routing and framework HTTP errors, such as 404 or 405."""
    return JSONResponse(
        status_code=exc.status_code,
        content=framework_error_body(exc.status_code, str(exc.detail)),
        headers=exc.headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the service's exception handlers to ``app``."""
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
