"""Request models for holder authentication.

Field names, patterns and ``extra`` handling copy the DCS schemas the
wallet app was written against, so the app's requests validate here
exactly as they did there.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.features.holders.schemas import ContactNumber

# DCS password rule for new passwords: 8+ letters, digits or !@#$%^&*.
NewPassword = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z\d!@#$%^&*]{8,}$", max_length=128),
]
ExistingPassword = Annotated[str, Field(min_length=8, max_length=128)]
HolderDid = Annotated[str, StringConstraints(pattern=r"^did:evrc:.+$")]


class OtpType(StrEnum):
    """Channel an OTP is sent over."""

    EMAIL = "email"
    MOBILE = "mobile"


class ValidateHolderRequest(BaseModel):
    """Body of ``POST /v1/holder/validate``: one of email or DID."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    did: HolderDid | None = None


class LoginRequest(BaseModel):
    """Body of ``POST /v1/holder/login``: email or DID, and password."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    did: HolderDid | None = None
    password: ExistingPassword


class RecoverRequest(BaseModel):
    """Body of ``POST /v1/holder/recover``."""

    model_config = ConfigDict(extra="forbid")

    recovery_token: str = Field(min_length=1, max_length=1024)


class RegisterRequest(BaseModel):
    """Body of ``POST /v1/holder/register``.

    Unknown fields are accepted and ignored, as in the DCS
    ``CreateHolder`` schema.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    contact: ContactNumber | None = None
    password: NewPassword
    confirm_password: NewPassword


class SendOtpRequest(BaseModel):
    """Body of ``POST /v1/wallet/holder/otp/send``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    mobile: str | None = Field(default=None, max_length=20)
    otp_type: OtpType


class VerifyOtpRequest(BaseModel):
    """Body of ``POST /v1/wallet/holder/otp/verify``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    mobile: str | None = Field(default=None, max_length=20)
    otp_code: str = Field(min_length=1, max_length=10)
    otp_type: OtpType


class OtpLoginRequest(BaseModel):
    """Body of ``POST /v1/holder/login/otp``."""

    model_config = ConfigDict(extra="forbid")

    login_token: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    """Body of ``POST /v1/holder/forget``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ChangePasswordRequest(BaseModel):
    """Body of ``POST /v1/holder/password/change``."""

    model_config = ConfigDict(extra="forbid")

    current_password: ExistingPassword
    new_password: NewPassword
    confirm_password: NewPassword


class SsoType(StrEnum):
    """Providers named by ``sso_type`` on ``/v1/holder/login/sso``."""

    GMAIL = "gmail"
    LINKEDIN = "linkedin"
    OFFICE365 = "office365"


class SsoLoginRequest(BaseModel):
    """Body of ``POST /v1/holder/login/sso`` (the DCS ``SsoLogin``).

    Accepted so existing app requests validate, but never trusted: the
    holder's identity comes from the verified provider token only.
    """

    model_config = ConfigDict(extra="forbid")

    provider_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = None
    profile_image: str | None = Field(default=None, max_length=2048)
    contact: str | None = Field(default=None, max_length=20)


class EmailConfirmationRequest(BaseModel):
    """Body of ``POST /v1/holder/email/confirmation``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
