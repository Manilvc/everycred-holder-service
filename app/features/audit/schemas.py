"""Response models for the holder audit trail."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    """One recorded action."""

    model_config = ConfigDict(from_attributes=True)

    action: str
    resource_type: str | None
    resource_id: str | None
    created_at: datetime
