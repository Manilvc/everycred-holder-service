"""Dependency providers for the notifications feature."""

from typing import Annotated

from fastapi import Depends

from app.core.config import SettingsDep
from app.core.database import DbSession
from app.features.notifications.service import (
    ConnectorEventService,
    InboxService,
)


def get_inbox_service(db_session: DbSession) -> InboxService:
    """Build an inbox service bound to the request's session."""
    return InboxService(session=db_session)


def get_connector_event_service(
    db_session: DbSession, settings: SettingsDep
) -> ConnectorEventService:
    """Build a connector event service bound to the request's session."""
    return ConnectorEventService(session=db_session, settings=settings)


InboxServiceDep = Annotated[InboxService, Depends(get_inbox_service)]
ConnectorEventServiceDep = Annotated[
    ConnectorEventService, Depends(get_connector_event_service)
]
