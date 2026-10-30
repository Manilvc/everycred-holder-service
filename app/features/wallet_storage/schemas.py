"""Request model for presentation storage (DCS ``HolderStorage``)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class HolderStorageRequest(BaseModel):
    """Body of ``POST /v1/holder/storage``.

    ``data`` is the verifiable presentation the wallet built. The window
    sets how long the returned URL works.
    """

    data: dict[str, Any]
    valid_from: datetime | None = None
    valid_until: datetime | None = None
