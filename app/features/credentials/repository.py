"""Database access for the holder's integer credential references."""

import uuid
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import generate_public_id
from app.features.credentials.models import CredentialRef

CredentialKey = tuple[str, str]

# One retry covers a concurrent request creating the same references;
# a third try only matters if a fresh numeric id also collides.
_ENSURE_ATTEMPTS = 3


class CredentialRefRepository:
    """Queries and persistence for :class:`CredentialRef` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, holder_id: uuid.UUID, numeric_id: int
    ) -> CredentialRef | None:
        """Return the holder's reference with ``numeric_id``, if any."""
        return await self.session.scalar(
            select(CredentialRef).where(
                CredentialRef.holder_id == holder_id,
                CredentialRef.numeric_id == numeric_id,
            )
        )

    async def ensure(
        self, holder_id: uuid.UUID, keys: Collection[CredentialKey]
    ) -> dict[CredentialKey, CredentialRef]:
        """Return a reference for every (source, credential) pair.

        Existing references are read in one query; missing ones are
        created together with ids checked for collisions in one more
        query. Safe to run concurrently for the same holder. The caller
        commits.

        Raises:
            IntegrityError: The references still collided after
                ``_ENSURE_ATTEMPTS`` tries.
        """
        if not keys:
            return {}
        refs = await self._refs_by_key(holder_id)
        for attempt in range(1, _ENSURE_ATTEMPTS + 1):
            missing = [key for key in dict.fromkeys(keys) if key not in refs]
            if not missing:
                return refs
            try:
                new_refs = await self._create(holder_id, missing)
            except IntegrityError:
                if attempt == _ENSURE_ATTEMPTS:
                    raise
                # The wallet loads its credential tabs in parallel, so
                # another request may have created these first. A
                # locking read sees its committed rows; a plain read
                # would still return this transaction's snapshot under
                # MySQL's REPEATABLE READ.
                refs = await self._refs_by_key(holder_id, latest=True)
                continue
            refs.update(
                {(ref.source_code, ref.credential_id): ref for ref in new_refs}
            )
        return refs

    async def _refs_by_key(
        self, holder_id: uuid.UUID, *, latest: bool = False
    ) -> dict[CredentialKey, CredentialRef]:
        query = select(CredentialRef).where(
            CredentialRef.holder_id == holder_id
        )
        if latest:
            query = query.with_for_update()
        rows = await self.session.scalars(query)
        return {(ref.source_code, ref.credential_id): ref for ref in rows}

    async def _create(
        self, holder_id: uuid.UUID, keys: list[CredentialKey]
    ) -> list[CredentialRef]:
        # A savepoint keeps a collision from rolling back the caller's
        # whole transaction.
        async with self.session.begin_nested():
            new_ids = await self._unused_ids(len(keys))
            new_refs = [
                CredentialRef(
                    holder_id=holder_id,
                    source_code=source_code,
                    credential_id=credential_id,
                    numeric_id=numeric_id,
                )
                for (source_code, credential_id), numeric_id in zip(
                    keys, new_ids, strict=True
                )
            ]
            self.session.add_all(new_refs)
        return new_refs

    async def _unused_ids(self, count: int) -> list[int]:
        # Drawing a few spare candidates means a collision with an
        # existing id (astronomically unlikely) never runs short.
        candidates = list({generate_public_id() for _ in range(count + 4)})
        taken = set(
            await self.session.scalars(
                select(CredentialRef.numeric_id).where(
                    CredentialRef.numeric_id.in_(candidates)
                )
            )
        )
        return [value for value in candidates if value not in taken][:count]
