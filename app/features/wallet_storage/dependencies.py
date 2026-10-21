"""Dependency providers for the wallet storage feature."""

from typing import Annotated

from fastapi import Depends

from app.core.config import SettingsDep
from app.core.database import DbSession
from app.core.storage import Storage
from app.features.wallet_storage.service import PresentationStorageService


def get_presentation_storage_service(
    db_session: DbSession, storage: Storage, settings: SettingsDep
) -> PresentationStorageService:
    """Build a presentation storage service for the request."""
    return PresentationStorageService(
        session=db_session, storage=storage, settings=settings
    )


PresentationStorageServiceDep = Annotated[
    PresentationStorageService, Depends(get_presentation_storage_service)
]
