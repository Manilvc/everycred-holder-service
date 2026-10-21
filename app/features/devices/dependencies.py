"""Dependency providers for the devices feature."""

from typing import Annotated

from fastapi import Depends

from app.core.database import DbSession
from app.features.devices.service import PushTokenService


def get_push_token_service(db_session: DbSession) -> PushTokenService:
    """Build a push token service bound to the request's session."""
    return PushTokenService(session=db_session)


PushTokenServiceDep = Annotated[
    PushTokenService, Depends(get_push_token_service)
]
