"""HTTP routes for the holder's credentials."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.connector import NormalizedCredential, OperationResponse
from app.features.auth.dependencies import CurrentHolder
from app.features.credentials.dependencies import CredentialServiceDep
from app.features.credentials.schemas import (
    CredentialEmailRequest,
    CredentialListResponse,
    CredentialShareResponse,
)
from app.shared.identifiers import ExternalId, SourceCode
from app.shared.schemas import ErrorResponse

router = APIRouter(tags=["Credentials"])

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}}
_UPSTREAM_ERRORS = {status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse}}


@router.get(
    "/credentials",
    response_model=CredentialListResponse,
    summary="List my credentials",
    responses=_UPSTREAM_ERRORS,
)
async def list_credentials(
    holder: CurrentHolder, service: CredentialServiceDep
) -> CredentialListResponse:
    """Return credentials from every DCS source issued to the holder."""
    return await service.list_credentials(holder)


@router.get(
    "/credentials/{credential_id}",
    response_model=NormalizedCredential,
    summary="Get one of my credentials",
    responses={**_NOT_FOUND, **_UPSTREAM_ERRORS},
)
async def get_credential(
    credential_id: ExternalId,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> NormalizedCredential:
    """Return a credential; 404 if it is not the holder's."""
    return await service.get_credential(holder, credential_id)


@router.get(
    "/credentials/{credential_id}/share",
    response_model=CredentialShareResponse,
    summary="Get the share link of a credential",
    responses={**_NOT_FOUND, **_UPSTREAM_ERRORS},
)
async def share_credential(
    credential_id: ExternalId,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> CredentialShareResponse:
    """Return the public verification link and QR code URL."""
    return await service.share_credential(holder, credential_id)


@router.get(
    "/credentials/{credential_id}/download",
    summary="Download a credential document",
    response_class=JSONResponse,
    responses={**_NOT_FOUND, **_UPSTREAM_ERRORS},
)
async def download_credential(
    credential_id: ExternalId,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> JSONResponse:
    """Return the W3C credential JSON as a file download."""
    credential = await service.download_credential(holder, credential_id)
    return JSONResponse(
        credential.credential_json,
        headers={
            "Content-Disposition": (
                f'attachment; filename="credential-{credential_id}.json"'
            )
        },
    )


@router.post(
    "/credentials/{credential_id}/email",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a credential link",
    responses={
        **_NOT_FOUND,
        **_UPSTREAM_ERRORS,
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
async def email_credential(
    credential_id: ExternalId,
    payload: CredentialEmailRequest,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> None:
    """Send the credential's verification link to a recipient."""
    await service.email_credential(
        holder, credential_id, payload.recipient_email, payload.note
    )


@router.get(
    "/sources/{source_code}/credentials/{credential_id}/stats",
    response_model=OperationResponse,
    summary="Get verification statistics of a credential",
    responses={**_NOT_FOUND, **_UPSTREAM_ERRORS},
)
async def get_credential_stats(
    source_code: SourceCode,
    credential_id: ExternalId,
    holder: CurrentHolder,
    service: CredentialServiceDep,
) -> OperationResponse:
    """Return the source's verification analytics for a credential."""
    return await service.get_verification_stats(
        holder, source_code, credential_id
    )
