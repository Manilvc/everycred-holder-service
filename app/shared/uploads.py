"""Helpers for reading request bodies and uploaded files safely."""

from fastapi import Request

from app.core.exceptions import PayloadTooLargeError

_IMAGE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}


async def read_body_limited(request: Request, max_bytes: int) -> bytes:
    """Read the raw request body, refusing anything over ``max_bytes``.

    The body is streamed, so an oversized request is rejected as soon
    as the limit is passed instead of being buffered in full.

    Raises:
        PayloadTooLargeError: The body is larger than ``max_bytes``.
    """
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise PayloadTooLargeError(
                f"The request body must not exceed {max_bytes} bytes."
            )
    return bytes(body)


def detect_image_type(content: bytes) -> str | None:
    """Return the image media type from the file's magic bytes.

    The declared ``Content-Type`` of an upload is chosen by the client,
    so the bytes themselves decide what is stored. WebP is recognised by
    its RIFF container header.
    """
    for media_type, signatures in _IMAGE_SIGNATURES.items():
        if content.startswith(signatures):
            return media_type
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None
