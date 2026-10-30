"""Database access for pending invites and registration reports."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.holders.models import Holder
from app.features.onboarding.models import (
    PendingInvite,
    RegistrationReport,
    ReportStatus,
)


class OnboardingRepository:
    """Queries and persistence for the onboarding feature."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, row: PendingInvite | RegistrationReport) -> None:
        """Stage a new row for insertion."""
        self.session.add(row)

    async def list_invites(self, email_key: str) -> Sequence[PendingInvite]:
        """Return the invites waiting for this email, oldest first."""
        rows = await self.session.scalars(
            select(PendingInvite)
            .where(PendingInvite.email_key == email_key)
            .order_by(PendingInvite.created_at)
        )
        return rows.all()

    async def delete_invites(self, invite_ids: Sequence[uuid.UUID]) -> None:
        """Delete the given invites in one statement."""
        if not invite_ids:
            return
        await self.session.execute(
            delete(PendingInvite).where(PendingInvite.id.in_(invite_ids))
        )

    async def has_pending_report(
        self, holder_id: uuid.UUID, operation: str
    ) -> bool:
        """Return True if an all-sources report is already waiting."""
        report_id = await self.session.scalar(
            select(RegistrationReport.id)
            .where(
                RegistrationReport.holder_id == holder_id,
                RegistrationReport.operation == operation,
                RegistrationReport.source_code.is_(None),
                RegistrationReport.status == ReportStatus.PENDING.value,
            )
            .limit(1)
        )
        return report_id is not None

    async def list_due_reports(
        self, now: datetime, limit: int
    ) -> Sequence[tuple[RegistrationReport, Holder]]:
        """Return due pending reports with their holder."""
        rows = await self.session.execute(
            select(RegistrationReport, Holder)
            .join(Holder, Holder.id == RegistrationReport.holder_id)
            .where(
                RegistrationReport.status == ReportStatus.PENDING.value,
                RegistrationReport.next_attempt_at <= now,
            )
            .order_by(RegistrationReport.next_attempt_at)
            .limit(limit)
        )
        return [(report, holder) for report, holder in rows]
