"""HTTP routes for holder device keys and DID resolution."""

from typing import Annotated

from fastapi import APIRouter, Path, status
from fastapi.responses import JSONResponse

from app.features.auth.dependencies import CurrentHolder
from app.features.dids.dependencies import DidServiceDep
from app.features.dids.schemas import HolderKeyCreate, HolderKeyResponse
from app.shared.schemas import ErrorResponse

keys_router = APIRouter(prefix="/holders/me/keys", tags=["Holder Keys"])
dids_router = APIRouter(prefix="/dids", tags=["DIDs"])

KeyId = Annotated[str, Path(pattern=r"^key-[0-9a-f]{16}$")]
Did = Annotated[str, Path(pattern=r"^did:[a-z0-9]+(:[A-Za-z0-9._-]+)+$")]


@keys_router.post(
    "",
    response_model=HolderKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a device public key",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def register_key(
    payload: HolderKeyCreate,
    holder: CurrentHolder,
    service: DidServiceDep,
) -> HolderKeyResponse:
    """Publish a public key generated on the device in the holder's DID.

    Only the public JWK (Ed25519 or P-256) is accepted. A JWK carrying
    private members such as ``d`` is rejected with 422.
    """
    return await service.register_key(holder, payload.public_jwk)


@keys_router.get(
    "",
    response_model=list[HolderKeyResponse],
    summary="List my active keys",
)
async def list_keys(
    holder: CurrentHolder, service: DidServiceDep
) -> list[HolderKeyResponse]:
    """Return the keys currently published in the holder's DID."""
    return await service.list_keys(holder)


@keys_router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a key",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def revoke_key(
    key_id: KeyId, holder: CurrentHolder, service: DidServiceDep
) -> None:
    """Remove a key from the DID document, e.g. after losing a device."""
    await service.revoke_key(holder, key_id)


@dids_router.get(
    "/{did}",
    summary="Resolve a holder DID",
    response_class=JSONResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def resolve_did(did: Did, service: DidServiceDep) -> JSONResponse:
    """Return the DID document with the holder's active public keys.

    Public: verifiers resolve holder DIDs to check presentations.
    """
    document = await service.resolve(did)
    return JSONResponse(
        document.model_dump(by_alias=True),
        media_type="application/did+json",
    )
