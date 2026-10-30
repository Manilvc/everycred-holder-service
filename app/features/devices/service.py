"""Registering and removing the push token of the current device."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.features.auth.models import HolderSession
from app.features.devices.models import PushToken
from app.features.devices.repository import PushTokenRepository
from app.features.devices.schemas import (
    RegisterPushTokenRequest,
    UnregisterPushTokenRequest,
)
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
        payload: RegisterPushTokenRequest,
    ) -> dict[str, Any]:
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
        push_token.device_label = payload.device_label
        push_token.app_version = payload.app_version
        push_token.is_active = True
        await self.session.commit()
        return {"uuid": str(push_token.id), "platform": push_token.platform}

    async def unregister(
        self, holder: Holder, payload: UnregisterPushTokenRequest
    ) -> None:
        """Stop pushes to one of the holder's tokens.

        Raises:
            NotFoundError: The token is unknown or another holder's; the
                two cases look the same so tokens cannot be probed.
        """
        push_token = await self.push_tokens.get_by_token(payload.token)
        if push_token is None or push_token.holder_id != holder.id:
            raise NotFoundError(
                "This device isn't registered for notifications."
            )
        push_token.is_active = False
        await self.session.commit()
