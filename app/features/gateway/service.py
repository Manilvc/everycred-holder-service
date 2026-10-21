"""Forwarding of issuer-side wallet actions through the connector.

Credential requests, workflow-engine steps, integration KYC sessions,
and DigiLocker flows live in the DCS that issued the request. This
service owns none of that data; it adds the authenticated holder's
email and forwards the action, and the connector calls the right DCS.
List operations fan out to every source the holder is linked to.
"""

from typing import Any

from app.core.connector import ConnectorClient, OperationResponse
from app.features.holders.models import Holder


class GatewayService:
    """Runs connector operations on behalf of the signed-in holder.

    Attributes:
        connector: Client for the connector service.
    """

    def __init__(self, connector: ConnectorClient) -> None:
        self.connector = connector

    async def list_from_all_sources(
        self, holder: Holder, operation: str
    ) -> OperationResponse:
        """Run a list operation against every source of the holder."""
        return await self.connector.run_operation(holder.email, operation)

    async def run_on_source(
        self,
        holder: Holder,
        operation: str,
        source_code: str,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> OperationResponse:
        """Run an item operation against one source."""
        return await self.connector.run_operation(
            holder.email,
            operation,
            source_code=source_code,
            params=params,
            body=body,
        )
