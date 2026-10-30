"""Issuer invites and reporting holder registrations to DCS sources.

An issuer invites a holder by email in a DCS. The DCS reports
``holder.invited`` to the connector, which links the email to the DCS
and forwards the event here:

* If the email has an account, the invite goes to the inbox at once and
  the registration is reported back to that DCS, so the issuer portal
  shows the holder as registered.
* Otherwise the invite waits in ``pending_invites`` (email hashed). When
  the email registers, :meth:`OnboardingService.claim_invites` moves the
  invites to the inbox and queues a report to every linked DCS.

Each registration is followed by a ``holder.profile_updated`` report
with the holder's own name and contact number, and so is every later
change to them, so issuer portals show the holder's current details.

Reports go through an outbox: :class:`RegistrationReportService`, run by
the worker, sends the connector operation and retries with backoff, so
a DCS that is down still hears about the change later. Profile reports
read the holder when they are sent, so a retry carries the latest
values. The DCS side is idempotent, so a retry that reaches a source a
second time changes nothing.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.connector import ConnectorClient, OperationResponse
from app.core.exceptions import (
    ExternalServiceError,
    NotFoundError,
    UpstreamRejectedError,
)
from app.core.models import utc_now
from app.core.security import hash_secret_value
from app.features.holders.models import Holder
from app.features.notifications.messages import build_invite_notification
from app.features.notifications.repository import NotificationRepository
from app.features.onboarding.models import (
    PROFILE_UPDATED_OPERATION,
    REGISTERED_OPERATION,
    PendingInvite,
    RegistrationReport,
    ReportStatus,
)
from app.features.onboarding.repository import OnboardingRepository

logger = logging.getLogger(__name__)

# Same schedule as notification deliveries; the last value repeats.
RETRY_BACKOFF_SECONDS = (30, 120, 600, 1800, 3600)
# Source answers worth retrying: a DCS that is down or overloaded, or
# whose connector key is being rotated. Any other answer, including 404
# for a holder the DCS no longer has, will not change on a retry.
_RETRYABLE_SOURCE_STATUSES = frozenset({401, 403, 429})
_MAX_ERROR_LENGTH = 255


def _email_key(email: str, settings: Settings) -> str:
    return hash_secret_value(email.strip().lower(), settings)


class OnboardingService:
    """Records invites and queues registration reports.

    Leaves committing to the caller, so the rows land in the same
    transaction as the event or registration that produced them.

    Attributes:
        settings: Hash secret for invite email keys.
        onboarding: Persistence for invites and reports.
        notifications: Persistence for inbox rows and deliveries.
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.settings = settings
        self.onboarding = OnboardingRepository(session)
        self.notifications = NotificationRepository(session)

    def hold_invite(
        self, email: str, source_code: str, inviter_name: str | None
    ) -> None:
        """Keep an invite for an email that has no account yet."""
        self.onboarding.add(
            PendingInvite(
                email_key=_email_key(email, self.settings),
                source_code=source_code,
                inviter_name=inviter_name,
            )
        )

    def queue_report(
        self, holder_id: uuid.UUID, source_code: str | None
    ) -> None:
        """Queue the registration and the profile to one source, or all.

        Args:
            holder_id: Holder that has an account.
            source_code: Source to tell; None tells every linked source.
        """
        for operation in (REGISTERED_OPERATION, PROFILE_UPDATED_OPERATION):
            self.onboarding.add(
                RegistrationReport(
                    holder_id=holder_id,
                    source_code=source_code,
                    operation=operation,
                    next_attempt_at=utc_now(),
                )
            )

    async def queue_profile_report(self, holder_id: uuid.UUID) -> None:
        """Queue the holder's profile to every linked source.

        Skipped when one is already waiting: it reads the holder when
        sent, so it carries this change too.
        """
        if await self.onboarding.has_pending_report(
            holder_id, PROFILE_UPDATED_OPERATION
        ):
            return
        self.onboarding.add(
            RegistrationReport(
                holder_id=holder_id,
                source_code=None,
                operation=PROFILE_UPDATED_OPERATION,
                next_attempt_at=utc_now(),
            )
        )

    async def claim_invites(self, holder: Holder) -> int:
        """Move the email's pending invites to the holder's inbox.

        Also queues a report to every source the holder is linked to,
        invited or not: a DCS that only issued credentials to the email
        tracks the holder's registration too.

        Returns:
            The number of invites moved.
        """
        invites = await self.onboarding.list_invites(
            _email_key(holder.email, self.settings)
        )
        if invites:
            await self.notifications.add_notifications(
                [
                    build_invite_notification(
                        holder.id, invite.source_code, invite.inviter_name
                    )
                    for invite in invites
                ]
            )
            await self.onboarding.delete_invites(
                [invite.id for invite in invites]
            )
        self.queue_report(holder.id, None)
        return len(invites)


class RegistrationReportService:
    """Sends due registration and profile reports. Used by the worker.

    Attributes:
        session: Unit of work; the service commits its own changes.
        settings: Maximum attempts.
        connector: Runs each report's connector operation.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        connector: ConnectorClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.connector = connector
        self.onboarding = OnboardingRepository(session)

    async def deliver_due(self, batch_size: int) -> int:
        """Attempt every due report once; return how many ran."""
        due = await self.onboarding.list_due_reports(utc_now(), batch_size)
        for report, holder in due:
            await self._send(report, holder)
        await self.session.commit()
        return len(due)

    async def _send(self, report: RegistrationReport, holder: Holder) -> None:
        body = (
            _profile_body(holder)
            if report.operation == PROFILE_UPDATED_OPERATION
            else None
        )
        try:
            response = await self.connector.run_operation(
                holder.email,
                report.operation,
                source_code=report.source_code,
                body=body,
            )
        except ExternalServiceError as exc:
            self._schedule_retry(report, exc.message)
            return
        except (NotFoundError, UpstreamRejectedError) as exc:
            # The named source is gone or no longer linked to the holder.
            self._finish(report, ReportStatus.FAILED, exc.message)
            return
        retry_reason = _retry_reason(response)
        if retry_reason:
            self._schedule_retry(report, retry_reason)
            return
        self._finish(report, ReportStatus.DONE)
        logger.info(
            "%s for holder %s reported to %d source(s)",
            report.operation,
            report.holder_id,
            len(response.items),
        )

    def _schedule_retry(self, report: RegistrationReport, error: str) -> None:
        report.attempts += 1
        report.last_error = error[:_MAX_ERROR_LENGTH]
        if report.attempts >= self.settings.notification_max_attempts:
            report.status = ReportStatus.FAILED.value
            logger.warning(
                "Registration report %s gave up after %s attempts",
                report.id,
                report.attempts,
            )
            return
        backoff_index = min(report.attempts, len(RETRY_BACKOFF_SECONDS)) - 1
        report.next_attempt_at = utc_now() + timedelta(
            seconds=RETRY_BACKOFF_SECONDS[backoff_index]
        )

    @staticmethod
    def _finish(
        report: RegistrationReport,
        status: ReportStatus,
        note: str | None = None,
    ) -> None:
        report.attempts += 1
        report.status = status.value
        report.last_error = note[:_MAX_ERROR_LENGTH] if note else None


def _profile_body(holder: Holder) -> dict[str, Any]:
    """Return the profile fields a DCS shows on its issuer screens."""
    return {"name": holder.full_name, "mobile": holder.mobile}


def _retry_reason(response: OperationResponse) -> str | None:
    """Return why the report must be sent again, or None if it is done."""
    failed_sources = [
        item.source_code
        for item in response.items
        if item.status_code >= 500
        or item.status_code in _RETRYABLE_SOURCE_STATUSES
    ]
    if not failed_sources:
        return None
    return f"no answer from {', '.join(sorted(failed_sources))}"
