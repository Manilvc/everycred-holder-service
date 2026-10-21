"""Reading the holder's own audit trail."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.audit.repository import AuditRepository
from app.features.audit.schemas import AuditLogResponse
from app.shared.schemas import Page


class AuditService:
    """Lists a holder's recorded actions."""

    def __init__(self, session: AsyncSession) -> None:
        self.audit = AuditRepository(session)

    async def list_logs(
        self, holder_id: uuid.UUID, limit: int, offset: int
    ) -> Page[AuditLogResponse]:
        """Return one page of the holder's actions, newest first."""
        rows, total = await self.audit.list_for_holder(
            holder_id, limit, offset
        )
        return Page[AuditLogResponse](
            items=[AuditLogResponse.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
