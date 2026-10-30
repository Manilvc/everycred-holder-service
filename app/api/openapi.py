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

## Wallet compatibility

The routes the wallet app calls keep the DCS backend's paths, bodies,
status codes and messages, so the app only changes
`EXPO_PUBLIC_API_BASE_URL` to `<this host>/v1`. See
`docs/wallet_compatibility.md`.

## Authentication

Holders sign in with `POST /v1/holder/login` (email or DID and
password) and send `data.token` as `Authorization: Bearer <token>`. A
token is bound to its session: changing or resetting the password, or
deleting the account, ends sessions and their tokens stop working.

The connector authenticates its webhooks with the
`X-EveryCRED-Signature` HMAC instead of a token.

## Responses

Every response, success or error, uses the DCS envelope:

```json
{"status": "fail", "data": null, "message": "Invalid token"}
```

`status` is `"success"` for 200, 201 and 202 and `"fail"` otherwise.
Missing tokens, validation errors and unknown routes put the numeric
HTTP status there instead, as the DCS does. `message` is meant to be
shown to the user.

## Forwarded actions

Credential request, workflow, integration KYC, and DigiLocker routes
return one item per DCS source called, each with that source's
`status_code`, `ok`, `data`, and `message`.
"""

OPENAPI_TAGS: list[dict[str, Any]] = [
    {"name": "Health", "description": "Liveness and readiness probes."},
    {
        "name": "Holder Account",
        "description": (
            "Registration with an emailed OTP, sign-in with email or DID, "
            "password change and reset, and account deletion and "
            "recovery. Paths and messages match the DCS backend."
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
            "connector, in the DCS response shapes. Nothing is stored "
            "by this service. The public lookup and verification "
            "analytics routes need no token."
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
            "Holder Account",
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
