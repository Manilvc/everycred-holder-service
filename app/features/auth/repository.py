"""Database access for sessions, OTPs, and password reset tokens."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.auth.models import (
    EmailOtp,
    HolderSession,
    PasswordResetToken,
)


class AuthRepository:
    """Queries and persistence for the auth feature's tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, row: HolderSession | EmailOtp | PasswordResetToken) -> None:
        """Stage a new row for insertion."""
        self.session.add(row)

    async def get_session(self, session_id: uuid.UUID) -> HolderSession | None:
        """Return the session with ``session_id``, if any."""
        return await self.session.get(HolderSession, session_id)

    async def end_sessions(
        self,
        holder_id: uuid.UUID,
        ended_at: datetime,
        *,
        except_session_id: uuid.UUID | None = None,
    ) -> Sequence[uuid.UUID]:
        """End a holder's open sessions and return their ids.

        Args:
            holder_id: Holder whose sessions are ended.
            ended_at: Time recorded as the end.
            except_session_id: Session to keep open, typically the one
                making the request.
        """
        conditions = [
            HolderSession.holder_id == holder_id,
            HolderSession.ended_at.is_(None),
        ]
        if except_session_id is not None:
            conditions.append(HolderSession.id != except_session_id)
        session_ids = (
            await self.session.scalars(
                select(HolderSession.id).where(*conditions)
            )
        ).all()
        if session_ids:
            await self.session.execute(
                update(HolderSession)
                .where(HolderSession.id.in_(session_ids))
                .values(ended_at=ended_at)
            )
        return session_ids

    async def get_latest_otp(self, email: str) -> EmailOtp | None:
        """Return the most recently issued OTP for ``email``."""
        return await self.session.scalar(
            select(EmailOtp)
            .where(EmailOtp.email == email)
            .order_by(EmailOtp.created_at.desc())
            .limit(1)
        )

    async def get_otp_by_login_token(
        self, login_token_hash: str
    ) -> EmailOtp | None:
        """Return the OTP that issued the login token, if any."""
        return await self.session.scalar(
            select(EmailOtp).where(
                EmailOtp.login_token_hash == login_token_hash
            )
        )

    async def claim_login_token(
        self, otp_id: uuid.UUID, signed_in_at: datetime
    ) -> bool:
        """Mark an OTP's login token used; False if it already was.

        A conditional update, so two concurrent requests with the same
        token cannot both claim it.
        """
        result = await self.session.execute(
            update(EmailOtp)
            .where(EmailOtp.id == otp_id, EmailOtp.signed_in_at.is_(None))
            .values(signed_in_at=signed_in_at)
        )
        return result.rowcount == 1

    async def get_reset_token(
        self, token_hash: str
    ) -> PasswordResetToken | None:
        """Return the reset token with ``token_hash``, if any."""
        return await self.session.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash
            )
        )

    async def consume_open_reset_tokens(
        self, holder_id: uuid.UUID, consumed_at: datetime
    ) -> None:
        """Invalidate every unused reset token of a holder."""
        await self.session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.holder_id == holder_id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at)
        )
