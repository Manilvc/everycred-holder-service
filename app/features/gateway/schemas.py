"""Request models for the DCS-shaped credential request routes."""

from pydantic import BaseModel, ConfigDict, Field

from app.shared.identifiers import EXTERNAL_ID_PATTERN


class RequestSubmission(BaseModel):
    """Body of ``POST /v1/holder/request/submission`` (DCS shape).

    Forwarded to the issuing DCS unchanged once its source is found.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=EXTERNAL_ID_PATTERN)
    slug: str = Field(max_length=200_000)
    digilocker_id: str | None = Field(default=None, max_length=128)
