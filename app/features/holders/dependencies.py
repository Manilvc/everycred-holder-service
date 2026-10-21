"""Dependency providers for the holders feature."""

from typing import Annotated

from fastapi import Depends

from app.core.database import DbSession
from app.core.storage import Storage
from app.features.holders.service import HolderProfileService


def get_holder_profile_service(
    db_session: DbSession, storage: Storage
) -> HolderProfileService:
    """Build a profile service bound to the request's session."""
    return HolderProfileService(session=db_session, storage=storage)


HolderProfileServiceDep = Annotated[
    HolderProfileService, Depends(get_holder_profile_service)
]
