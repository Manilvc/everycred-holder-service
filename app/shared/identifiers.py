"""Path parameter types for ids that belong to DCS sources.

These ids are forwarded to the connector and on to a DCS instance, so
they are restricted to the same safe character set the connector
accepts. That keeps them from changing the shape of a forwarded URL.
"""

from typing import Annotated

from fastapi import Path

EXTERNAL_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"
SOURCE_CODE_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

ExternalId = Annotated[str, Path(pattern=EXTERNAL_ID_PATTERN)]
SourceCode = Annotated[
    str,
    Path(
        pattern=SOURCE_CODE_PATTERN,
        description="Code of the DCS source, as returned in list results.",
    ),
]
