# `app/core/signatures.py`

> Last updated: 2026-10-21

## Purpose

Verify webhooks from the EveryCRED connector. The scheme is the one the
integration service and the connector use for all EveryCRED webhooks.

## Public API

- `EVENT_HEADER`, `DELIVERY_HEADER`, `SIGNATURE_HEADER` — header names.
- `encode_body(payload) -> bytes` — compact, key-sorted JSON, exactly as
  the sender signs it. Used by tests to build signed requests.
- `sign(secret, timestamp, body) -> str` — `t=<unix>,v1=<hex HMAC>`.
- `is_signature_valid(secret, header, body, tolerance_seconds, now=None)`
  — returns False for a malformed header, a timestamp outside the
  tolerance, or a wrong HMAC.

```python
from app.core.signatures import is_signature_valid

if not is_signature_valid(secret, header, raw_body, 300):
    raise InvalidEventSignatureError("The signature is invalid.")
```

## How it works

1. The sender computes HMAC-SHA256 over `"<t>.<raw body>"` with the
   shared secret and sends `X-EveryCRED-Signature: t=<t>,v1=<hex>`.
2. The receiver recomputes it over the raw bytes it received (never a
   re-serialised copy) and compares with `hmac.compare_digest`.
3. A timestamp more than the tolerance away from now is rejected, so a
   captured request cannot be replayed later. Replays inside the window
   are caught by the receiver's `X-EveryCRED-Delivery` de-duplication.

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `CONNECTOR_WEBHOOK_SECRET` | required | Shared secret |
| `WEBHOOK_TOLERANCE_SECONDS` | `300` | Maximum clock difference |

## Failure modes

The function never raises; callers turn `False` into
`InvalidEventSignatureError` (401).

## Changing this module

Keep the scheme identical to the connector's `app/core/signatures.py`;
both sides must change together.

## Tests

`tests/core/test_signatures.py` and
`tests/features/notifications/test_connector_events.py`.
