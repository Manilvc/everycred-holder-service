"""Registering and removing the push token of the current device."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.auth.models import HolderSession
from app.features.devices.models import PushToken
from app.features.devices.repository import PushTokenRepository
from app.features.devices.schemas import PushTokenRegister, PushTokenResponse
from app.features.holders.models import Holder


class PushTokenService:
    """Binds FCM tokens to holder sessions.

    Attributes:
        session: Unit of work; the service commits its own changes.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.push_tokens = PushTokenRepository(session)

    async def register(
        self,
        holder: Holder,
        holder_session: HolderSession,
        payload: PushTokenRegister,
    ) -> PushTokenResponse:
        """Upsert the token and bind it to the current session.

        A token already known (same device, perhaps another holder) is
        moved to this holder and session rather than duplicated.
        """
        push_token = await self.push_tokens.get_by_token(payload.token)
        if push_token is None:
            push_token = PushToken(token=payload.token)
            self.push_tokens.add(push_token)
        push_token.holder_id = holder.id
        push_token.session_id = holder_session.id
        push_token.platform = payload.platform.value
        push_token.is_active = True
        await self.session.commit()
        return PushTokenResponse(platform=payload.platform, is_active=True)

    async def unregister(self, holder_session: HolderSession) -> None:
        """Stop pushes to the tokens of the current session."""
        await self.push_tokens.deactivate_for_sessions([holder_session.id])
        await self.session.commit()
