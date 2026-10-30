"""Request models and field rules for the holder profile.

Field names, patterns and ``extra`` handling copy the DCS schemas the
wallet app was written against (``UpdateHolder`` and friends).
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# DCS rule: optional "+", then 10 digits not starting with 0.
ContactNumber = Annotated[str, StringConstraints(pattern=r"^\+?[1-9]\d{9}$")]

# Base64 of an image up to a few MB; the decoded size is checked against
# MAX_PROFILE_IMAGE_BYTES in the service.
_MAX_BASE64_CHARS = 16 * 1024 * 1024


class UpdateHolder(BaseModel):
    """Body of ``PUT /v1/holder/update``; omitted fields stay as they are.

    ``profile_image`` is raw base64 without a ``data:`` prefix, as the
    wallet app sends it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    contact: ContactNumber | None = None
    profile_image: str | None = Field(
        default=None, min_length=1, max_length=_MAX_BASE64_CHARS
    )
