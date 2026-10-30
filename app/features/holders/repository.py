"""Database access for holder accounts."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import generate_public_id
from app.features.holders.models import Holder

# Candidates drawn per pick. One collision among 2**52 values is already
# astronomically unlikely, so several at once never all collide.
_NUMERIC_ID_CANDIDATES = 4


class HolderRepository:
    """Queries and persistence for :class:`Holder` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, holder_id: uuid.UUID) -> Holder | None:
        """Return the holder with ``holder_id``, if any."""
        return await self.session.get(Holder, holder_id)

    async def get_by_email(self, email: str) -> Holder | None:
        """Return the holder registered with ``email`` (lower-cased).

        Deleted accounts are included; callers check ``is_deleted``.
        """
        return await self.session.scalar(
            select(Holder).where(Holder.email == email.lower())
        )

    async def get_by_did(self, did: str) -> Holder | None:
        """Return the holder that owns ``did``."""
        return await self.session.scalar(
            select(Holder).where(Holder.did == did)
        )

    async def get_by_email_or_did(self, identifier: str) -> Holder | None:
        """Return the holder whose email or DID equals ``identifier``."""
        return await self.session.scalar(
            select(Holder).where(
                or_(
                    Holder.email == identifier.lower(),
                    Holder.did == identifier,
                )
            )
        )

    async def pick_unused_numeric_id(self) -> int:
        """Return a random public id no holder uses yet, in one query."""
        candidates = {
            generate_public_id() for _ in range(_NUMERIC_ID_CANDIDATES)
        }
        taken = set(
            await self.session.scalars(
                select(Holder.numeric_id).where(
                    Holder.numeric_id.in_(candidates)
                )
            )
        )
        return next(iter(candidates - taken))

    def add(self, holder: Holder) -> None:
        """Stage a new holder for insertion."""
        self.session.add(holder)

    async def delete(self, holder: Holder) -> None:
        """Remove a holder row and, by cascade, everything it owns."""
        await self.session.delete(holder)
