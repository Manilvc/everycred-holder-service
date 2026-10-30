"""Authentication dependencies and auth service providers.

:data:`CurrentHolder` is what every holder-facing route depends on. It
verifies the bearer token and then checks, on every request, that the
session in the token is still open and the holder still active. That
database check is what lets logout and password changes revoke tokens
immediately without a token blacklist.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import SettingsDep
from app.core.database import DbSession
from app.core.email import Mailer
from app.core.exceptions import AuthenticationError, NotAuthenticatedError
from app.core.http_client import HttpClient
from app.core.models import utc_now
from app.core.security import TokenType, decode_token
from app.core.storage import Storage
from app.features.auth.google import GoogleIdTokenVerifier
from app.features.auth.models import HolderSession
from app.features.auth.repository import AuthRepository
from app.features.auth.service import AuthService
from app.features.dids.service import DidProvisioner
from app.features.holders.models import Holder
from app.features.holders.repository import HolderRepository

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The authenticated holder and the session the token belongs to."""

    holder: Holder
    session: HolderSession


def _parse_uuid(value: str | None) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise AuthenticationError("Invalid token") from exc


async def get_auth_context(
    db_session: DbSession,
    settings: SettingsDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(_bearer_scheme)
    ],
) -> AuthContext:
    """Return the holder and session behind the request's bearer token.

    Raises:
        NotAuthenticatedError: No bearer token was sent.
        AuthenticationError: An invalid token, or a token whose session
            has ended or expired, or whose holder is inactive or deleted.
            Every case returns the DCS message "Invalid token".
    """
    if credentials is None:
        raise NotAuthenticatedError("Not authenticated")
    claims = decode_token(credentials.credentials, TokenType.ACCESS, settings)
    holder_session = await AuthRepository(db_session).get_session(
        _parse_uuid(claims.session_id)
    )
    if (
        holder_session is None
        or holder_session.ended_at is not None
        or holder_session.expires_at <= utc_now()
        or str(holder_session.holder_id) != claims.subject
    ):
        raise AuthenticationError("Invalid token")
    holder = await HolderRepository(db_session).get_by_id(
        holder_session.holder_id
    )
    if holder is None or not holder.is_active or holder.is_deleted:
        raise AuthenticationError("Invalid token")
    return AuthContext(holder=holder, session=holder_session)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


def get_current_holder(auth: CurrentAuth) -> Holder:
    """Return the authenticated holder."""
    return auth.holder


CurrentHolder = Annotated[Holder, Depends(get_current_holder)]


def get_google_id_token_verifier(
    http_client: HttpClient, settings: SettingsDep
) -> GoogleIdTokenVerifier:
    """Build a verifier for Google sign-in with the shared HTTP client."""
    return GoogleIdTokenVerifier(http_client, settings.google_client_ids)


def get_auth_service(
    db_session: DbSession,
    settings: SettingsDep,
    mailer: Mailer,
    storage: Storage,
    google_verifier: Annotated[
        GoogleIdTokenVerifier, Depends(get_google_id_token_verifier)
    ],
) -> AuthService:
    """Build an auth service bound to the request's session."""
    return AuthService(
        session=db_session,
        settings=settings,
        mailer=mailer,
        did_provisioner=DidProvisioner(storage, settings),
        google_verifier=google_verifier,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
