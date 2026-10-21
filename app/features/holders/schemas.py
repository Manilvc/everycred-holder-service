"""Request and response models for the holder profile."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.features.auth.schemas import MobileNumber


class HolderProfileResponse(BaseModel):
    """The signed-in holder's profile, with short-lived file URLs."""

    id: uuid.UUID
    email: str
    did: str
    full_name: str
    mobile: str | None
    profile_image_url: str | None
    did_qr_code_url: str | None
    did_profile_url: str | None
    created_at: datetime


class HolderProfileUpdate(BaseModel):
    """Fields a holder may change; omitted fields stay as they are."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    mobile: MobileNumber | None = None
