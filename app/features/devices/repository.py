"""Database access for push tokens."""

import uuid
from collections.abc import Collection, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.devices.models import PushToken


class PushTokenRepository:
    """Queries and persistence for :class:`PushToken` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_token(self, token: str) -> PushToken | None:
        """Return the row for an FCM token, if registered."""
        return await self.session.scalar(
            select(PushToken).where(PushToken.token == token)
        )

    def add(self, push_token: PushToken) -> None:
        """Stage a new token for insertion."""
        self.session.add(push_token)

    async def deactivate_for_sessions(
        self, session_ids: Collection[uuid.UUID]
    ) -> None:
        """Stop pushes to every token registered by these sessions."""
        if not session_ids:
            return
        await self.session.execute(
            update(PushToken)
            .where(PushToken.session_id.in_(session_ids))
            .values(is_active=False)
        )

    async def deactivate_tokens(
        self, token_ids: Collection[uuid.UUID]
    ) -> None:
        """Deactivate tokens FCM reported as no longer valid."""
        if not token_ids:
            return
        await self.session.execute(
            update(PushToken)
            .where(PushToken.id.in_(token_ids))
            .values(is_active=False)
        )

    async def list_active_for_holders(
        self, holder_ids: Collection[uuid.UUID]
    ) -> Sequence[PushToken]:
        """Return the active tokens of all ``holder_ids`` in one query."""
        if not holder_ids:
            return []
        rows = await self.session.scalars(
            select(PushToken).where(
                PushToken.holder_id.in_(holder_ids),
                PushToken.is_active.is_(True),
            )
        )
        return rows.all()
