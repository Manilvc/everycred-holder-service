"""Verification of Google ID tokens for wallet sign-in.

The wallet signs the holder in with Google and sends the ID token it
received. The token's signature is checked against Google's published
certificates, which are fetched with the shared HTTP client (so the
call has a timeout and does not block the event loop); decoding and the
audience check use ``google-auth``.
"""

import logging
from dataclasses import dataclass

import httpx
from google.auth import jwt as google_jwt

from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_ISSUERS = frozenset(
    {"accounts.google.com", "https://accounts.google.com"}
)
# Tolerated difference between Google's clock and ours.
CLOCK_SKEW_SECONDS = 30


class InvalidGoogleTokenError(Exception):
    """Raised when an ID token is not a valid, verified Google sign-in."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    """The verified account behind a Google ID token."""

    subject: str
    email: str


class GoogleIdTokenVerifier:
    """Checks Google ID tokens issued to this service's OAuth clients.

    Attributes:
        http_client: Shared client used to fetch Google's certificates.
        client_ids: OAuth client ids a token's audience must match.
    """

    def __init__(
        self, http_client: httpx.AsyncClient, client_ids: list[str]
    ) -> None:
        self.http_client = http_client
        self.client_ids = client_ids

    @property
    def is_configured(self) -> bool:
        """Return True when at least one client id is accepted."""
        return bool(self.client_ids)

    async def verify(self, id_token: str) -> GoogleIdentity:
        """Return the verified account behind ``id_token``.

        Raises:
            InvalidGoogleTokenError: The token is malformed, expired,
                not issued by Google, meant for another client, or for
                an unverified email.
            ExternalServiceError: Google's certificates could not be
                fetched.
        """
        certs = await self._fetch_certs()
        try:
            claims = google_jwt.decode(
                id_token,
                certs=certs,
                audience=self.client_ids,
                clock_skew_in_seconds=CLOCK_SKEW_SECONDS,
            )
        except ValueError as exc:
            raise InvalidGoogleTokenError("invalid ID token") from exc
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise InvalidGoogleTokenError("unexpected issuer")
        email = claims.get("email")
        if not email or claims.get("email_verified") is not True:
            raise InvalidGoogleTokenError("email not verified")
        return GoogleIdentity(subject=str(claims["sub"]), email=email.lower())

    async def _fetch_certs(self) -> dict[str, str]:
        try:
            response = await self.http_client.get(GOOGLE_CERTS_URL)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Fetching Google certificates failed: %s", type(exc).__name__
            )
            raise ExternalServiceError(
                "Google sign-in is unavailable. Please try again."
            ) from exc
