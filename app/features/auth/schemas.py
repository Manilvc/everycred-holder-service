"""Request and response models for holder authentication."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

Password = Annotated[str, Field(min_length=8, max_length=128)]
OtpCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]
MobileNumber = Annotated[str, StringConstraints(pattern=r"^\+?[0-9]{7,15}$")]


class OtpSendRequest(BaseModel):
    """Ask for a registration code to be emailed."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class OtpVerifyRequest(BaseModel):
    """Prove control of an email with the code sent to it."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    code: OtpCode


class RegistrationTokenResponse(BaseModel):
    """Short-lived token that lets the verified email register."""

    registration_token: str
    expires_at: datetime


class RegisterRequest(BaseModel):
    """Create a holder account for a verified email."""

    model_config = ConfigDict(extra="forbid")

    registration_token: str = Field(max_length=2048)
    password: Password
    full_name: str = Field(min_length=1, max_length=150)
    mobile: MobileNumber | None = None


class LoginRequest(BaseModel):
    """Sign in with an email or DID and a password."""

    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(
        min_length=3,
        max_length=320,
        description="The holder's email address or DID.",
    )
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Access token for a new session."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - scheme name
    expires_at: datetime
    holder_id: uuid.UUID
    did: str


class ChangePasswordRequest(BaseModel):
    """Replace the password; other sessions are signed out."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password


class ForgotPasswordRequest(BaseModel):
    """Ask for a password reset link to be emailed."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Set a new password with the token from the reset link."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=128)
    new_password: Password


class AcceptedResponse(BaseModel):
    """Acknowledgement that does not reveal whether an account exists."""

    message: str
