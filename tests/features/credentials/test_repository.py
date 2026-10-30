import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.features.credentials.models import CredentialRef
from app.features.credentials.repository import (
    CredentialKey,
    CredentialRefRepository,
)
from tests.conftest import RegisteredHolder

KEY: CredentialKey = ("dcs-india", "cred-1")


async def test_ensure_reuses_a_reference_another_request_created(
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder_id = uuid.UUID(holder.uuid)
    async with session_factory() as session:
        winner = await CredentialRefRepository(session).ensure(
            holder_id, [KEY]
        )
        await session.commit()
    winner_id = winner[KEY].numeric_id

    async with session_factory() as session:
        repository = CredentialRefRepository(session)
        read_latest = repository._refs_by_key

        async def stale_snapshot(
            holder_id: uuid.UUID, *, latest: bool = False
        ) -> dict[CredentialKey, CredentialRef]:
            # Before the winner's commit is visible, the first read
            # finds nothing, as in a parallel request.
            if not latest:
                return {}
            return await read_latest(holder_id, latest=True)

        monkeypatch.setattr(repository, "_refs_by_key", stale_snapshot)
        refs = await repository.ensure(holder_id, [KEY])
        await session.commit()

        count = await session.scalar(
            select(func.count()).select_from(CredentialRef)
        )

    assert refs[KEY].numeric_id == winner_id
    assert count == 1
