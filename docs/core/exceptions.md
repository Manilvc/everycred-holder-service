# `app/core/exceptions.py` and `app/core/responses.py`

> Last updated: 2026-10-22

## Purpose

Let services report failures without knowing about HTTP, and make every
response use the DCS envelope the wallet app reads:

```json
{ "status": "fail", "data": null, "message": "Invalid token" }
```

The app decides success from the HTTP status code and shows `message`
to the user, so messages must be safe and readable.

## Public API

### `app/core/responses.py`

- `respond(status_code, message, data=None, headers=None) -> JSONResponse`
  — success responses from routers. `status` is `"success"` for 200,
  201 and 202, `"fail"` otherwise; falsy `data` becomes `null`, as in the
  DCS `StandardResponse`.
- `build_envelope(status_code, message, data=None) -> dict` — the same
  envelope as a dict (used by the error handlers and the middleware).
- `framework_error_body(status_code, message, **extra) -> dict` — the
  DCS shape for framework errors, with the numeric status in `status`.

```python
from fastapi import status

from app.core.responses import respond

return respond(status.HTTP_200_OK, "Holder retrieved successfully!", detail)
```

### Error classes

| Class | Status | Use when |
|-------|--------|----------|
| `AppError` | 400 | Base class; generic client error |
| `AuthenticationError` | 401 | Invalid or expired token, ended session |
| `NotAuthenticatedError` | 401 | No bearer token (envelope `status` is `401`) |
| `PermissionDeniedError` | 403 | Authenticated but not allowed |
| `NotFoundError` | 404 | Resource absent (or not the holder's) |
| `ConflictError` | 409 | Duplicate or invalid state transition |
| `PayloadTooLargeError` | 413 | An upload or request body is too big |
| `UnprocessableError` | 422 | Well-formed request with unusable content |
| `TooManyRequestsError` | 429 | A per-holder or per-email limit was hit |
| `ExternalServiceError` | 502 | The connector or SMTP relay failed |
| `UpstreamRejectedError` | 400 | The connector rejected the request |

`AppError(message, data=None)`: `data` is returned in the envelope
where the DCS contract puts details there, for example the remaining OTP
attempts or the empty credential bucket. `error_code` is kept for logs
only; the wallet does not see it.

## How it works

| Handler | Catches | Response |
|---------|---------|----------|
| `handle_app_error` | `AppError` subclasses | Class status, `{"status": "fail", "data", "message"}`; logged at `INFO` |
| `handle_validation_error` | `RequestValidationError` | `422 {"status": 422, "data": null, "message": "<field> <msg>", "errors": [{"field", "message", "type"}]}` |
| `handle_http_error` | Starlette `HTTPException` (unknown route, wrong method) | Same status, `{"status": <code>, "data": null, "message": <detail>}` |

`_summarise_validation_errors` keeps only the field, message and type.
Pydantic also includes the rejected `input`, which could be a password
or an OTP, so it is dropped.

Unexpected exceptions are handled in
[middleware](middleware.md#why-crashes-are-handled-here), which answers
500 with the generic DCS message.

## Changing this module

- Keep messages identical to the DCS where the wallet app shows them;
  see [wallet_compatibility.md](../wallet_compatibility.md).
- Do not raise `fastapi.HTTPException` from services; raise an
  `AppError` subclass instead.

## Tests

`tests/core/test_error_handling.py`.
