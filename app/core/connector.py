"""Client for the EveryCRED connector service.

The holder service stores no credentials and owns no issuer data. Every
credential, credential request, workflow step, KYC session, and
DigiLocker flow lives in a DCS instance; the connector knows which one
and forwards the call. This module is the only place that talks to it.

Every call is scoped to the holder's email: the connector only returns
data that the source DCS links to that email, which is how ownership is
enforced without this service knowing about credentials at all.

Errors from the connector use the shared envelope
``{"error": {"code", "message", "request_id"}}`` and are mapped to
:class:`~app.core.exceptions.AppError` subclasses here, so services and
routes never see HTTP details.
"""

import logging
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, Request
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, SettingsDep
from app.core.exceptions import (
    ExternalServiceError,
    NotFoundError,
    UpstreamRejectedError,
)

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"


class CredentialIssuer(BaseModel):
    """Issuer details of a normalised credential."""

    name: str | None = None
    did: str | None = None
    email: str | None = None
    logo_url: str | None = None
    description: str | None = None


class NormalizedCredential(BaseModel):
    """A credential in the connector's source-independent shape."""

    credential_id: str
    source_code: str
    status: Literal["issued", "revoked"]
    title: str | None = None
    holder_name: str | None = None
    issuer: CredentialIssuer = CredentialIssuer()
    issued_at: str | None = None
    fields: dict[str, Any] = {}
    credential_url: str | None = None
    image_url: str | None = None
    qr_code_url: str | None = None
    hash: str | None = None
    credential_json: dict[str, Any] | None = None


class CredentialLookupItem(BaseModel):
    """One credential found for a holder, or why it could not be loaded."""

    source_code: str
    credential_id: str
    status: Literal["issued", "revoked"]
    credential: NormalizedCredential | None = None
    error: str | None = None


class CredentialLookupResponse(BaseModel):
    """Every credential the connector routes to a holder."""

    items: list[CredentialLookupItem]


class OperationResult(BaseModel):
    """What one DCS source answered to a forwarded operation."""

    source_code: str
    status_code: int
    ok: bool
    data: Any = None
    message: str | None = None


class OperationResponse(BaseModel):
    """Per-source results of a forwarded operation."""

    items: list[OperationResult]


class ConnectorClient:
    """Calls the connector on behalf of one holder at a time.

    Attributes:
        http_client: Shared outbound client from the lifespan.
        settings: Source of the connector URL, key and timeout.
    """

    def __init__(
        self, http_client: httpx.AsyncClient, settings: Settings
    ) -> None:
        self.http_client = http_client
        self.settings = settings

    async def lookup_credentials(
        self, holder_email: str
    ) -> CredentialLookupResponse:
        """Return every credential issued to ``holder_email``."""
        payload = await self._post(
            "/v1/holders/credentials/lookup", {"holder_email": holder_email}
        )
        return self._parse(CredentialLookupResponse, payload)

    async def get_credential(
        self, holder_email: str, credential_id: str
    ) -> NormalizedCredential:
        """Return one credential, if it belongs to ``holder_email``.

        Raises:
            NotFoundError: No such credential for this holder.
        """
        payload = await self._post(
            "/v1/holders/credentials/get",
            {"holder_email": holder_email, "credential_id": credential_id},
        )
        return self._parse(NormalizedCredential, payload)

    async def run_operation(
        self,
        holder_email: str,
        operation: str,
        *,
        source_code: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> OperationResponse:
        """Forward a wallet action to the DCS source(s) of the holder.

        Args:
            holder_email: Holder the action is performed for.
            operation: Connector operation name, e.g. ``requests.get``.
            source_code: Source to call; None fans out to every source
                the holder is linked to (list operations only).
            params: Path values the operation needs.
            body: JSON body passed to the source unchanged.
        """
        payload = await self._post(
            "/v1/holders/operations",
            {
                "holder_email": holder_email,
                "operation": operation,
                "source_code": source_code,
                "params": params or {},
                "body": body,
            },
        )
        return self._parse(OperationResponse, payload)

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self.settings.connector_base_url.rstrip('/')}{path}"
        try:
            response = await self.http_client.post(
                url,
                json=body,
                headers={
                    API_KEY_HEADER: (
                        self.settings.connector_api_key.get_secret_value()
                    )
                },
                timeout=self.settings.connector_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            logger.warning("Connector call to %s timed out", path)
            raise ExternalServiceError(
                "The credential network did not answer in time."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "Connector call to %s failed: %s", path, type(exc).__name__
            )
            raise ExternalServiceError(
                "The credential network is unavailable."
            ) from exc
        if response.is_success:
            return response.json()
        raise self._error_for(path, response)

    @staticmethod
    def _error_for(path: str, response: httpx.Response) -> Exception:
        error_code, message = "connector_error", None
        try:
            error = response.json().get("error") or {}
            error_code = str(error.get("code") or error_code)
            message = error.get("message")
        except (ValueError, AttributeError):
            pass
        if response.status_code == httpx.codes.NOT_FOUND:
            return NotFoundError(message or "The resource was not found.")
        if response.status_code in (
            httpx.codes.BAD_REQUEST,
            httpx.codes.UNPROCESSABLE_ENTITY,
        ):
            return UpstreamRejectedError(
                message or "The request was rejected.", error_code
            )
        logger.error(
            "Connector call to %s answered HTTP %s (%s)",
            path,
            response.status_code,
            error_code,
        )
        return ExternalServiceError("The credential network is unavailable.")

    @staticmethod
    def _parse[ModelT: BaseModel](model: type[ModelT], payload: Any) -> ModelT:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            logger.error("Connector returned an unexpected %s", model.__name__)
            raise ExternalServiceError(
                "The credential network returned an invalid response."
            ) from exc


def get_connector_client(
    request: Request, settings: SettingsDep
) -> ConnectorClient:
    """Build a connector client from the lifespan's HTTP client."""
    return ConnectorClient(
        http_client=request.state.http_client, settings=settings
    )


Connector = Annotated[ConnectorClient, Depends(get_connector_client)]
