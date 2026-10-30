"""Request models for the credential endpoints the wallet app calls."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CredentialType(StrEnum):
    """Bucket of ``GET /v1/user/holder/credentials``."""

    ISSUED = "issued"
    REVOKED = "revoked"
    EXPIRED = "expired"


class VerificationAnalyticsRequest(BaseModel):
    """Body of ``POST /v1/credential/verification/analytics``.

    Passed to the issuing DCS unchanged; the fields mirror the DCS
    ``AnalyticsSchema``.
    """

    model_config = ConfigDict(extra="ignore")

    verification_status: bool
    stage: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=1000)
    checkpoint_id: str | int | None = None


class CredentialEmailShareRequest(BaseModel):
    """Body of ``POST /v1/holder/send/email`` (the DCS ``CredentialShare``).

    The upper bound is ``MAX_SHARE_RECIPIENTS``, checked by the service;
    the limit here only bounds the request size.
    """

    model_config = ConfigDict(extra="forbid")

    holder_email: list[EmailStr] = Field(min_length=1, max_length=50)
