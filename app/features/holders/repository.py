"""Database access for holder accounts."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.holders.models import Holder


class HolderRepository:
    """Queries and persistence for :class:`Holder` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, holder_id: uuid.UUID) -> Holder | None:
        """Return the holder with ``holder_id``, if any."""
        return await self.session.get(Holder, holder_id)

    async def get_by_email(self, email: str) -> Holder | None:
        """Return the holder registered with ``email`` (lower-cased)."""
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

    def add(self, holder: Holder) -> None:
        """Stage a new holder for insertion."""
        self.session.add(holder)
