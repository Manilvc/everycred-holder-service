"""Verification of webhooks signed by the EveryCRED connector.

The scheme is shared by every EveryCRED service that sends webhooks::

    X-EveryCRED-Event: credential.issued
    X-EveryCRED-Delivery: <delivery id>
    X-EveryCRED-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256>

The HMAC covers ``"<t>.<raw body>"`` with the shared secret. The
receiver recomputes it over the raw bytes it received, compares in
constant time, and rejects timestamps outside the tolerance window so a
captured request cannot be replayed later.
"""

import hashlib
import hmac
import json
import time
from typing import Any

EVENT_HEADER = "X-EveryCRED-Event"
DELIVERY_HEADER = "X-EveryCRED-Delivery"
SIGNATURE_HEADER = "X-EveryCRED-Signature"


def encode_body(payload: dict[str, Any]) -> bytes:
    """Serialise a payload exactly as the connector signs and sends it."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """Return the signature header value for ``body``."""
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def is_signature_valid(
    secret: str,
    header: str,
    body: bytes,
    tolerance_seconds: int,
    now: float | None = None,
) -> bool:
    """Return True if ``header`` is a fresh, valid signature of ``body``."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        received = parts["v1"]
    except (KeyError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        return False
    expected = sign(secret, timestamp, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, received)
