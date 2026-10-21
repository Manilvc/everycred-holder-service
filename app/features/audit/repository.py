"""Database access for the holder audit trail."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.audit.models import AuditAction, HolderAuditLog


class AuditRepository:
    """Writes and reads :class:`HolderAuditLog` rows.

    Writes are only staged; the service that owns the unit of work
    commits them together with the change they describe.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def record(
        self,
        holder_id: uuid.UUID,
        action: AuditAction,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        """Stage an audit entry for ``holder_id``."""
        self.session.add(
            HolderAuditLog(
                holder_id=holder_id,
                action=action.value,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )

    async def list_for_holder(
        self, holder_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[Sequence[HolderAuditLog], int]:
        """Return one page of a holder's entries, newest first, and total."""
        condition = HolderAuditLog.holder_id == holder_id
        total = await self.session.scalar(
            select(func.count()).select_from(HolderAuditLog).where(condition)
        )
        rows = await self.session.scalars(
            select(HolderAuditLog)
            .where(condition)
            .order_by(HolderAuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return rows.all(), total or 0

    async def count_since(
        self, holder_id: uuid.UUID, action: AuditAction, since: datetime
    ) -> int:
        """Count a holder's ``action`` entries created after ``since``."""
        count = await self.session.scalar(
            select(func.count())
            .select_from(HolderAuditLog)
            .where(
                HolderAuditLog.holder_id == holder_id,
                HolderAuditLog.action == action.value,
                HolderAuditLog.created_at >= since,
            )
        )
        return count or 0
