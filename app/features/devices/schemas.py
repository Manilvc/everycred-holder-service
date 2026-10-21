"""Request and response models for push tokens."""

from pydantic import BaseModel, ConfigDict, Field

from app.features.devices.models import DevicePlatform


class PushTokenRegister(BaseModel):
    """The FCM registration token of this wallet install."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(
        min_length=20, max_length=512, pattern=r"^[A-Za-z0-9_:\-.]+$"
    )
    platform: DevicePlatform


class PushTokenResponse(BaseModel):
    """Confirmation that pushes will reach this device."""

    platform: DevicePlatform
    is_active: bool
