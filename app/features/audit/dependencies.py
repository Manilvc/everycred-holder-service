"""Dependency providers for the audit feature."""

from typing import Annotated

from fastapi import Depends

from app.core.database import DbSession
from app.features.audit.service import AuditService


def get_audit_service(db_session: DbSession) -> AuditService:
    """Build an audit service bound to the request's session."""
    return AuditService(session=db_session)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
