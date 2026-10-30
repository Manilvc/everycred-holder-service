"""Dependency providers for the holders feature."""

from typing import Annotated

from fastapi import Depends

from app.core.config import SettingsDep
from app.core.database import DbSession
from app.core.storage import Storage
from app.features.holders.service import HolderProfileService


def get_holder_profile_service(
    db_session: DbSession, storage: Storage, settings: SettingsDep
) -> HolderProfileService:
    """Build a profile service bound to the request's session."""
    return HolderProfileService(
        session=db_session, storage=storage, settings=settings
    )


HolderProfileServiceDep = Annotated[
    HolderProfileService, Depends(get_holder_profile_service)
]
