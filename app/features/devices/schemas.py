"""Request models for push tokens (DCS ``RegisterPushTokenSchema``)."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.features.devices.models import DevicePlatform

# FCM registration tokens are URL-safe: letters, digits, '-', '_', ':'
# and '.'.
FcmToken = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=20,
        max_length=512,
        pattern=r"^[A-Za-z0-9_:\-.]+$",
    ),
]


class RegisterPushTokenRequest(BaseModel):
    """Body of ``PUT /v1/push/holder/token``; an idempotent upsert."""

    model_config = ConfigDict(extra="forbid")

    token: FcmToken
    platform: DevicePlatform
    device_label: str | None = Field(default=None, max_length=150)
    app_version: str | None = Field(default=None, max_length=50)


class UnregisterPushTokenRequest(BaseModel):
    """Body of ``DELETE /v1/push/holder/token``."""

    model_config = ConfigDict(extra="forbid")

    token: FcmToken
