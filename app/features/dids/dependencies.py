"""Dependency providers for the DIDs feature."""

from typing import Annotated

from fastapi import Depends

from app.core.config import SettingsDep
from app.core.database import DbSession
from app.features.dids.service import DidService


def get_did_service(
    db_session: DbSession, settings: SettingsDep
) -> DidService:
    """Build a DID service bound to the request's session."""
    return DidService(session=db_session, settings=settings)


DidServiceDep = Annotated[DidService, Depends(get_did_service)]
