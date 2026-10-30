"""Response models shared by every feature.

Every response uses the DCS backend's envelope,
``{"status", "data", "message"}``, because the wallet app was built
against the DCS and reads ``message`` (and sometimes ``data``) from both
successes and errors. These models document that envelope in OpenAPI.
"""

from typing import Any

from pydantic import BaseModel, Field


class DcsResponse[DataT](BaseModel):
    """Envelope of every response.

    ``status`` is ``"success"`` for 200, 201 and 202 and ``"fail"`` for
    every other status code, except framework errors (missing token,
    validation, unknown route), where the DCS puts the numeric HTTP
    status there instead.
    """

    status: str | int = Field(examples=["success"])
    data: DataT | None = None
    message: str = Field(examples=["Holder retrieved successfully!"])


class ErrorResponse(BaseModel):
    """Envelope returned for every non-2xx response."""

    status: str | int = Field(examples=["fail"])
    data: Any = None
    message: str = Field(examples=["Invalid token"])


class Page[ItemT](BaseModel):
    """One page of results from a list endpoint."""

    items: list[ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
