# Wallet Storage

> Package: `app/features/wallet_storage/`
> Owner: EveryCRED backend team
> Last updated: 2026-10-21

## Overview

The wallet builds and signs a verifiable presentation on the device,
uploads it here, and shares the returned short-lived URL, for example as
a QR code. Replaces DCS `POST /v1/holder/storage`.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| POST | `/v1/holders/me/storage` | Store a presentation (multipart `file`) | bearer |

Response `201 Created`:

```json
{
  "presentation_id": "00000000-0000-0000-0000-000000000000",
  "url": "https://files.example.com/...",
  "url_expires_in_seconds": 900
}
```

Errors:

| Status | `error.code` | When |
|--------|--------------|------|
| 400 | `invalid_presentation` | Not a UTF-8 JSON object |
| 413 | `payload_too_large` | Over `MAX_PRESENTATION_BYTES` |

## Flow

Stored at `holders/<holder id>/presentations/<uuid>.json` and recorded
as `presentation_stored` in the audit trail.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `MAX_PRESENTATION_BYTES` | `1048576` | Upload limit |
| `STORAGE_URL_TTL_SECONDS` | `900` | URL lifetime (S3) |

## Known limitations

- Objects are not deleted automatically; add an S3 lifecycle rule on
  the `presentations/` prefix.
- The signature inside the presentation is not verified here; verifiers
  check it against the holder's DID document.

## Testing

`tests/features/wallet_storage/test_presentations.py`.
