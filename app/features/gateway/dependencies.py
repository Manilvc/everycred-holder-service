"""Dependency providers for the gateway feature."""

from typing import Annotated

from fastapi import Depends

from app.core.connector import Connector
from app.features.gateway.service import GatewayService


def get_gateway_service(connector: Connector) -> GatewayService:
    """Build a gateway service for the request."""
    return GatewayService(connector=connector)


GatewayServiceDep = Annotated[GatewayService, Depends(get_gateway_service)]
