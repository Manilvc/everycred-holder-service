"""Credential routes, at the DCS paths the wallet app calls.

The first four need the holder's token. The last two are the DCS public
verifier endpoints, which the app calls on the same base URL; they need
no token.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, status
from fastapi.responses import JSONResponse

from app.core.responses import respond
from app.features.auth.dependencies import CurrentHolder
from app.features.credentials.dependencies import CredentialServiceDep
from app.features.credentials.schemas import (
    CredentialEmailShareRequest,
    CredentialType,
    VerificationAnalyticsRequest,
)
from app.shared.identifiers import EXTERNAL_ID_PATTERN
from app.shared.schemas import DcsResponse, ErrorResponse

router = APIRouter(tags=["Credentials"])

AnyResponse = DcsResponse[Any]
_AUTH_ERRORS = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
}
CredentialRefId = Annotated[
    int, Query(ge=1, description="The credential's ``id`` from the list.")
]
CredentialUniqueId = Annotated[str, Path(pattern=EXTERNAL_ID_PATTERN)]


@router.get(
    "/user/holder/credentials",
    response_model=AnyResponse,
    summary="List my credentials",
    responses={
        **_AUTH_ERRORS,
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def list_credentials(
    holder_id: Annotated[int, Query()],
    type: Annotated[CredentialType, Query()],  # noqa: A002 - DCS name
    holder: CurrentHolder,
    service: CredentialServiceDep,
    page: Annotated[int, Query(ge=0)] = 1,
    per_page: Annotated[int, Query(ge=0, le=100)] = 0,
) -> JSONResponse:
    """Return one bucket (issued, revoked, expired) of credentials.

    ``holder_id`` must be the caller's ``id`` from ``GET /v1/holder``.
    An empty bucket answers 404 with ``data.total`` 0, as the DCS does.
    """
    result = await service.list_credentials(
        holder, holder_id, type, page, per_page
    )
    return respond(
        status.HTTP_200_OK, "Credentials are fetched successfully", result
    )


@router.get(
    "/holder/credential/share",
    response_model=AnyResponse,
    summary="Get what is needed to share a credential",
    responses=_AUTH_ERRORS,
)
async def share_credential(
    cred_id: CredentialRefId,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> JSONResponse:
    """Return the QR image, verifier link and logo of a credential."""
    result = await service.share_credential(holder, cred_id)
    return respond(
        status.HTTP_200_OK, "Credentials share successfully!", result
    )


@router.get(
    "/holder/credential/preview",
    response_model=AnyResponse,
    summary="Preview a credential's fields",
    responses=_AUTH_ERRORS,
)
async def preview_credential(
    cred_id: CredentialRefId,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> JSONResponse:
    """Return the credential's fields, validity and revocation state."""
    result = await service.preview_credential(holder, cred_id)
    return respond(
        status.HTTP_200_OK, "Credential preview fetched successfully!", result
    )


@router.get(
    "/holder/credential/download",
    response_model=AnyResponse,
    summary="Get the download link of a credential",
    responses={
        **_AUTH_ERRORS,
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
    },
)
async def download_credential(
    cred_id: CredentialRefId,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> JSONResponse:
    """Return ``{"credential": <link to the credential document>}``."""
    result = await service.download_credential(holder, cred_id)
    return respond(
        status.HTTP_200_OK, "Credential downloaded successfully!", result
    )


@router.post(
    "/holder/send/email",
    response_model=AnyResponse,
    summary="Email a credential to other people",
    responses={
        **_AUTH_ERRORS,
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
    },
)
async def email_credential(
    cred_id: CredentialRefId,
    payload: CredentialEmailShareRequest,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> JSONResponse:
    """Send each address the credential's verifier link and id."""
    await service.email_credential(
        holder, cred_id, [str(email) for email in payload.holder_email]
    )
    return respond(status.HTTP_200_OK, "Email sent successfully!")


@router.get(
    "/holder/stats",
    response_model=AnyResponse,
    summary="Get verification statistics of a credential",
    responses=_AUTH_ERRORS,
)
async def get_credential_stats(
    cred_id: CredentialRefId,
    page: Annotated[int, Query(ge=0)],
    per_page: Annotated[int, Query(ge=0, le=100)],
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> JSONResponse:
    """Return the issuing DCS's analytics for the credential.

    ``page`` and ``per_page`` are accepted for compatibility; the
    connector does not forward them yet, so the source's first page is
    returned.
    """
    status_code, message, data = await service.get_stats(holder, cred_id)
    return respond(status_code, message, data)


@router.get(
    "/holder/credential/notification",
    response_model=AnyResponse,
    summary="List issue and revoke notifications",
    responses=_AUTH_ERRORS,
)
async def list_credential_notifications(
    holder: CurrentHolder,
    service: CredentialServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 10,
) -> JSONResponse:
    """Return notifications newest first; empty is 200 with no items."""
    result = await service.list_notifications(holder, page, per_page)
    return respond(
        status.HTTP_200_OK, "Notification received successfully!", result
    )


@router.get(
    "/user/credential/{credential_unique_id}",
    response_model=AnyResponse,
    summary="Look up any credential (public verifier)",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)
async def get_public_credential(
    credential_unique_id: CredentialUniqueId,
    service: CredentialServiceDep,
) -> JSONResponse:
    """Return the credential in the DCS verifier shape; no token needed."""
    result = await service.get_public_credential(credential_unique_id)
    return respond(
        status.HTTP_200_OK, "Verification completed successfully!", result
    )


@router.post(
    "/credential/verification/analytics",
    response_model=AnyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a verification of a credential",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def record_verification(
    uuid: Annotated[
        str, Query(pattern=EXTERNAL_ID_PATTERN, description="Unique id")
    ],
    payload: VerificationAnalyticsRequest,
    service: CredentialServiceDep,
) -> JSONResponse:
    """Forward a verification result to the issuing DCS; no token needed."""
    status_code, message, data = await service.record_verification(
        uuid, payload
    )
    return respond(status_code, message, data)
