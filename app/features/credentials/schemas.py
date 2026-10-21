"""Request and response models for the holder's credentials."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.connector import CredentialLookupItem


class CredentialListResponse(BaseModel):
    """Every credential issued to the holder, across all DCS sources.

    An item whose source could not be reached has ``credential`` null
    and an ``error``; the others are still returned.
    """

    items: list[CredentialLookupItem]


class CredentialShareResponse(BaseModel):
    """What the wallet needs to share a credential."""

    credential_id: str
    source_code: str
    title: str | None
    share_url: str | None
    qr_code_url: str | None


class CredentialEmailRequest(BaseModel):
    """Send a link to a credential to someone by email."""

    model_config = ConfigDict(extra="forbid")

    recipient_email: EmailStr
    note: str | None = Field(default=None, max_length=500)
