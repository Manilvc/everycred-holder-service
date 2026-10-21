"""Database access for holder public keys."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.dids.models import HolderKey


class HolderKeyRepository:
    """Queries and persistence for :class:`HolderKey` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, key: HolderKey) -> None:
        """Stage a new key for insertion."""
        self.session.add(key)

    async def list_active(self, holder_id: uuid.UUID) -> Sequence[HolderKey]:
        """Return a holder's unrevoked keys, oldest first."""
        rows = await self.session.scalars(
            select(HolderKey)
            .where(
                HolderKey.holder_id == holder_id,
                HolderKey.revoked_at.is_(None),
            )
            .order_by(HolderKey.created_at)
        )
        return rows.all()

    async def count_active(self, holder_id: uuid.UUID) -> int:
        """Return how many unrevoked keys a holder has."""
        count = await self.session.scalar(
            select(func.count())
            .select_from(HolderKey)
            .where(
                HolderKey.holder_id == holder_id,
                HolderKey.revoked_at.is_(None),
            )
        )
        return count or 0

    async def get_active(
        self, holder_id: uuid.UUID, key_id: str
    ) -> HolderKey | None:
        """Return one unrevoked key of a holder by its key id."""
        return await self.session.scalar(
            select(HolderKey).where(
                HolderKey.holder_id == holder_id,
                HolderKey.key_id == key_id,
                HolderKey.revoked_at.is_(None),
            )
        )
