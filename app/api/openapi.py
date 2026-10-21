"""OpenAPI metadata rendered by ReDoc (``/redoc``) and Swagger (``/docs``).

Keeping the prose here keeps :mod:`app.main` about wiring. Tag names
must match the ``tags`` declared on each feature's router.
"""

from typing import Any

from fastapi import FastAPI

API_DESCRIPTION = """
API behind the EveryCRED holder wallet app. It owns holder accounts,
sessions, DIDs and device keys, notifications, and wallet storage.
Credentials, credential requests, and workflow steps stay in the DCS
that issued them; this service fetches and forwards them through the
EveryCRED connector and stores none of their content.

## Authentication

Holders sign in with `POST /v1/auth/login` (email or DID and password)
and send the returned token as `Authorization: Bearer <token>`. A token
is bound to its session: signing out, changing the password, or
resetting it ends sessions and their tokens stop working at once.

The connector authenticates its webhooks with the
`X-EveryCRED-Signature` HMAC instead of a token.

## Errors

Every error response has the same shape:

```json
{
  "error": {
    "code": "invalid_credentials",
    "message": "Invalid email, DID or password.",
    "request_id": "6f37b4e671f344f99e4a0736491737ea"
  }
}
```

`code` is stable and safe to branch on; `message` is for people.

## Forwarded actions

Credential request, workflow, integration KYC, and DigiLocker routes
return one item per DCS source called, each with that source's
`status_code`, `ok`, `data`, and `message`. List routes call every
source the holder is linked to; item routes take the `source_code`
from the list result.
"""

OPENAPI_TAGS: list[dict[str, Any]] = [
    {"name": "Health", "description": "Liveness and readiness probes."},
    {
        "name": "Auth",
        "description": (
            "Registration with an emailed OTP, sign-in with email or DID, "
            "sign-out, and password change and reset. Five wrong "
            "passwords lock the account for 15 minutes by default, and "
            "every sign-in failure returns the same error."
        ),
    },
    {"name": "Holder Profile", "description": "The signed-in holder."},
    {
        "name": "Holder Keys",
        "description": (
            "Public keys generated on the device, published in the "
            "holder's DID document. Private keys are never accepted."
        ),
    },
    {"name": "DIDs", "description": "Public DID resolution."},
    {"name": "Devices", "description": "Push notification tokens."},
    {"name": "Notifications", "description": "The holder's inbox."},
    {
        "name": "Credentials",
        "description": (
            "Credentials fetched live from the issuing DCS through the "
            "connector. Nothing is stored by this service."
        ),
    },
    {"name": "Credential Requests", "description": "Forwarded to DCS."},
    {"name": "Workflow Requests", "description": "Forwarded to DCS."},
    {"name": "Integration KYC", "description": "Forwarded to DCS."},
    {"name": "DigiLocker", "description": "Forwarded to DCS."},
    {
        "name": "Wallet Storage",
        "description": "Short-lived storage of presentations to share.",
    },
    {"name": "Audit", "description": "The holder's account activity."},
    {
        "name": "Connector Events",
        "description": (
            "Webhooks from the connector when a credential is issued or "
            "revoked, or a request changes. Signed with "
            '`X-EveryCRED-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "'
            '<t>.<body>">`.'
        ),
    },
]

TAG_GROUPS: list[dict[str, Any]] = [
    {
        "name": "Account",
        "tags": [
            "Auth",
            "Holder Profile",
            "Holder Keys",
            "Devices",
            "Notifications",
            "Wallet Storage",
            "Audit",
        ],
    },
    {
        "name": "Credentials and requests",
        "tags": [
            "Credentials",
            "Credential Requests",
            "Workflow Requests",
            "Integration KYC",
            "DigiLocker",
        ],
    },
    {
        "name": "Public and service-to-service",
        "tags": ["DIDs", "Connector Events", "Health"],
    },
]

LICENSE_INFO = {"name": "MIT", "identifier": "MIT"}


def add_redoc_extensions(app: FastAPI) -> None:
    """Add ReDoc-only extensions to the generated OpenAPI schema.

    FastAPI builds the schema lazily on the first request to
    ``/openapi.json`` and caches it; this wraps that step once so the
    extensions are included in the cached copy.
    """
    build_schema = app.openapi

    def openapi_with_tag_groups() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = build_schema()
            schema["x-tagGroups"] = TAG_GROUPS
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi_with_tag_groups  # type: ignore[method-assign]
