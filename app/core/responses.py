"""Builders for the DCS response envelope.

The wallet app was written against the DCS backend, whose responses are
``{"status": "success" | "fail", "data": ..., "message": "..."}``. The
app decides success from the HTTP status code and shows ``message`` to
the user as-is, so every route here answers in exactly that shape.

Like the DCS ``StandardResponse``, ``status`` is derived from the HTTP
status code, and any falsy ``data`` (``{}``, ``[]``, ``0``) becomes
``null``.
"""

from typing import Any

from fastapi import status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

STATUS_SUCCESS = "success"
STATUS_FAIL = "fail"
_SUCCESS_CODES = frozenset(
    {status.HTTP_200_OK, status.HTTP_201_CREATED, status.HTTP_202_ACCEPTED}
)


def build_envelope(
    status_code: int, message: str, data: Any = None
) -> dict[str, Any]:
    """Return the JSON-ready envelope for ``status_code``."""
    return {
        "status": (
            STATUS_SUCCESS if status_code in _SUCCESS_CODES else STATUS_FAIL
        ),
        "data": jsonable_encoder(data) if data else None,
        "message": message,
    }


def respond(
    status_code: int,
    message: str,
    data: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Return a response in the DCS envelope."""
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(status_code, message, data),
        headers=headers,
    )


def framework_error_body(
    status_code: int, message: str, **extra: Any
) -> dict[str, Any]:
    """Return the envelope the DCS uses for framework-level errors.

    Missing tokens, validation failures and unknown routes are reported
    by the DCS with the numeric HTTP status in ``status``.
    """
    return {"status": status_code, "data": None, "message": message, **extra}
