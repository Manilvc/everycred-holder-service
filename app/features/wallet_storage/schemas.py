"""Response models for presentation storage."""

import uuid

from pydantic import BaseModel


class StoredPresentationResponse(BaseModel):
    """Where a stored verifiable presentation can be fetched."""

    presentation_id: uuid.UUID
    url: str
    url_expires_in_seconds: int
