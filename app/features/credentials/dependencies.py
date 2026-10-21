"""Dependency providers for the credentials feature."""

from typing import Annotated

from fastapi import Depends

from app.core.config import SettingsDep
from app.core.connector import Connector
from app.core.database import DbSession
from app.core.email import Mailer
from app.features.credentials.service import CredentialService


def get_credential_service(
    db_session: DbSession,
    settings: SettingsDep,
    connector: Connector,
    mailer: Mailer,
) -> CredentialService:
    """Build a credential service for the request."""
    return CredentialService(
        session=db_session,
        settings=settings,
        connector=connector,
        mailer=mailer,
    )


CredentialServiceDep = Annotated[
    CredentialService, Depends(get_credential_service)
]
