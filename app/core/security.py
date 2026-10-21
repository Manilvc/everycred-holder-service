"""Password hashing, one-time secrets, and holder access tokens.

Passwords are hashed with Argon2id through :mod:`pwdlib`. Hashing is
deliberately slow (tens of milliseconds), so the async helpers run it in
a worker thread to keep the event loop free for other requests.

OTP codes and password reset tokens are short-lived, so a fast keyed
HMAC is enough for them; the server-side key means a leaked database
alone cannot be used to confirm a code.

Tokens are signed JWTs with a ``typ`` claim, so a registration token
can never be used as an access token or the other way round. Access
tokens also carry ``sid``, the holder session they belong to; route
dependencies check that the session is still active on every request.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.models import utc_now

TOKEN_AUDIENCE = "everycred-holder-service"  # noqa: S105 - not a secret
OTP_DIGITS = 6
_REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub", "typ", "jti"]

_password_hasher = PasswordHash((Argon2Hasher(),))


class TokenType(StrEnum):
    """What a signed token may be used for."""

    ACCESS = "access"
    REGISTRATION = "registration"


@dataclass(frozen=True, slots=True)
class PasswordCheck:
    """Outcome of comparing a password with a stored hash.

    Attributes:
        is_valid: Whether the password matched.
        updated_hash: A fresh hash to store when the hashing parameters
            have changed since the old one was created, otherwise None.
    """

    is_valid: bool
    updated_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SignedToken:
    """A signed token and when it stops being valid."""

    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Verified contents of a token.

    Attributes:
        subject: Holder id for access tokens, email for registration.
        session_id: Holder session id; only set on access tokens.
    """

    subject: str
    session_id: str | None
    expires_at: datetime


async def hash_password(password: str) -> str:
    """Return an Argon2id hash of ``password``."""
    return await run_in_threadpool(_password_hasher.hash, password)


async def verify_password(password: str, password_hash: str) -> PasswordCheck:
    """Check ``password`` against ``password_hash`` in constant time."""
    is_valid, updated_hash = await run_in_threadpool(
        _password_hasher.verify_and_update, password, password_hash
    )
    return PasswordCheck(is_valid=is_valid, updated_hash=updated_hash)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return _password_hasher.hash(uuid.uuid4().hex)


async def burn_password_check_time(password: str) -> None:
    """Spend the same time as a real check when the account is unknown.

    Without this, a login for an unknown email returns noticeably faster
    than one with a wrong password, which reveals which emails have
    accounts.
    """
    await run_in_threadpool(
        _password_hasher.verify, password, _dummy_password_hash()
    )


def generate_otp_code() -> str:
    """Return a random numeric one-time code."""
    return f"{secrets.randbelow(10**OTP_DIGITS):0{OTP_DIGITS}d}"


def generate_url_token() -> str:
    """Return a random token safe to put in a URL (256 bits)."""
    return secrets.token_urlsafe(32)


def hash_secret_value(value: str, settings: Settings) -> str:
    """Return the hex HMAC-SHA256 of an OTP code or reset token."""
    return hmac.new(
        settings.token_hash_secret.get_secret_value().encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


def is_secret_value_valid(
    value: str, stored_hash: str, settings: Settings
) -> bool:
    """Compare ``value`` with a stored hash in constant time."""
    return hmac.compare_digest(hash_secret_value(value, settings), stored_hash)


def _encode(claims: dict[str, Any], settings: Settings) -> str:
    return jwt.encode(
        claims,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _base_claims(
    subject: str,
    token_type: TokenType,
    expires_at: datetime,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "sub": subject,
        "typ": token_type.value,
        "iss": settings.service_name,
        "aud": TOKEN_AUDIENCE,
        "iat": utc_now(),
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }


def create_access_token(
    holder_id: uuid.UUID,
    session_id: uuid.UUID,
    expires_at: datetime,
    settings: Settings,
) -> SignedToken:
    """Sign an access token bound to one holder session."""
    claims = _base_claims(
        str(holder_id), TokenType.ACCESS, expires_at, settings
    )
    claims["sid"] = str(session_id)
    return SignedToken(token=_encode(claims, settings), expires_at=expires_at)


def create_registration_token(email: str, settings: Settings) -> SignedToken:
    """Sign a short-lived proof that ``email`` passed OTP verification."""
    expires_at = utc_now() + timedelta(
        minutes=settings.registration_token_minutes
    )
    claims = _base_claims(email, TokenType.REGISTRATION, expires_at, settings)
    return SignedToken(token=_encode(claims, settings), expires_at=expires_at)


def decode_token(
    token: str, expected_type: TokenType, settings: Settings
) -> TokenClaims:
    """Verify ``token`` and return its claims.

    Raises:
        AuthenticationError: The token is malformed, expired, signed
            with another key, of another type, or missing a claim. The
            reason is not exposed to the caller.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            # Pinning the algorithm list blocks "alg: none" and
            # algorithm-confusion attacks.
            algorithms=[settings.jwt_algorithm],
            audience=TOKEN_AUDIENCE,
            issuer=settings.service_name,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid or expired token.") from exc

    if claims["typ"] != expected_type.value:
        raise AuthenticationError("Invalid or expired token.")
    session_id = claims.get("sid")
    if expected_type is TokenType.ACCESS and not session_id:
        raise AuthenticationError("Invalid or expired token.")
    return TokenClaims(
        subject=claims["sub"],
        session_id=session_id,
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )
