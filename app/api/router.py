"""Versioned API router that collects every feature's routes.

Each feature exposes its own ``APIRouter``; this module is the single
place where they are mounted under ``/v1``. The routes the wallet app
calls keep the DCS backend's exact paths (see
``docs/wallet_compatibility.md``), so the app only changes its base URL.
"""

from fastapi import APIRouter, status

from app.features.audit.router import router as audit_router
from app.features.auth.router import router as auth_router
from app.features.credentials.router import router as credentials_router
from app.features.devices.router import router as devices_router
from app.features.dids.router import dids_router, keys_router
from app.features.gateway.router import router as gateway_router
from app.features.gateway.wallet_router import wallet_router as requests_router
from app.features.holders.router import router as holders_router
from app.features.notifications.router import (
    connector_router,
    inbox_router,
)
from app.features.wallet_storage.router import router as storage_router
from app.shared.schemas import ErrorResponse

api_v1_router = APIRouter(
    prefix="/v1",
    # Documented once here so every versioned route shows the shared
    # error envelope in OpenAPI.
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)

# Wallet app (DCS-compatible paths).
api_v1_router.include_router(auth_router)
api_v1_router.include_router(holders_router)
api_v1_router.include_router(storage_router)
api_v1_router.include_router(credentials_router)
api_v1_router.include_router(devices_router)
api_v1_router.include_router(requests_router)

# Holder service additions with no DCS equivalent the app uses.
api_v1_router.include_router(keys_router)
api_v1_router.include_router(dids_router)
api_v1_router.include_router(audit_router)
api_v1_router.include_router(inbox_router)
api_v1_router.include_router(gateway_router)
api_v1_router.include_router(connector_router)
