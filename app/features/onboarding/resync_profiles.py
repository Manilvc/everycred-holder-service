"""Queue a profile report for existing holders, so every DCS gets it again.

Profile reports now carry the holder's DID, which a DCS needs to issue
linked credentials. Holders who registered before that have a DCS row
without a DID; queueing one more ``holder.profile_updated`` report fills
it in. The worker (``python -m app.worker``) sends the reports; a DCS
never replaces a DID it already has, so re-sending is safe.

Usage::

    python -m app.features.onboarding.resync_profiles --email a@example.com
    python -m app.features.onboarding.resync_profiles --all
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import create_database_engine, create_session_factory
from app.features.holders.models import Holder
from app.features.onboarding.service import OnboardingService


async def queue_profile_reports(
    session: AsyncSession, settings: Settings, emails: Sequence[str] | None
) -> int:
    """Queue a profile report for the named holders, or all when None.

    Args:
        session: Session the reports are added to; committed here.
        settings: Service settings.
        emails: Holder emails to re-send; None means every holder.

    Returns:
        Number of holders a report was queued for (one already waiting
        counts, since it is sent with the current profile too).
    """
    query = select(Holder.id)
    if emails is not None:
        lowered = [email.strip().lower() for email in emails]
        query = query.where(func.lower(Holder.email).in_(lowered))
    holder_ids = (await session.scalars(query)).all()
    onboarding = OnboardingService(session, settings)
    for holder_id in holder_ids:
        await onboarding.queue_profile_report(holder_id)
    await session.commit()
    return len(holder_ids)


async def _run(emails: Sequence[str] | None) -> int:
    """Queue the reports against the configured database."""
    settings = get_settings()
    engine = create_database_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            return await queue_profile_reports(session, settings, emails)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, queue the reports and print how many."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--email", action="append", help="Holder email; repeat for more."
    )
    target.add_argument("--all", action="store_true", help="Every holder.")
    args = parser.parse_args(argv)

    queued = asyncio.run(_run(None if args.all else args.email))
    print(f"Queued a profile report for {queued} holder(s).")
    if args.email and queued < len(args.email):
        print("Some emails have no holder account; nothing queued for them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
