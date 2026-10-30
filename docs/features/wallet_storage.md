# Wallet storage

> Package: `app/features/wallet_storage/`
> Last updated: 2026-10-22

## Overview

Temporary storage of verifiable presentations the wallet shares. The
app uploads a presentation and puts the returned URL in a QR code; the
URL works for the window the app asks for.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| POST | `/v1/holder/storage` | Store a presentation | bearer |

### `POST /v1/holder/storage`

Request:

```json
{
  "data": { "@context": ["https://www.w3.org/ns/credentials/v2"], "type": ["VerifiablePresentation"] },
  "valid_from": "2026-10-22T10:00:00Z",
  "valid_until": "2026-10-22T10:10:00Z"
}
```

Response `201` "Data Uploaded Successfully!":

```json
{
  "file_path": "https://bucket.s3.amazonaws.com/holder-service/holders/<uuid>/presentations/<id>.json?X-Amz-...",
  "valid_from": "2026-10-22T10:00:00Z",
  "valid_until": "2026-10-22T10:10:00Z"
}
```

| Status | When |
|--------|------|
| 400 | `valid_until` not after `valid_from`, in the past, or the window is longer than allowed |
| 413 | Presentation larger than `MAX_PRESENTATION_BYTES` |

## Flow

`PresentationStorageService.store_presentation` checks the size and the
window, writes `holders/<uuid>/presentations/<id>.json`, and asks the
storage backend for a URL that expires at `valid_until`.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `MAX_PRESENTATION_BYTES` | `1048576` | Largest presentation |
| `PRESENTATION_DEFAULT_WINDOW_SECONDS` | `300` | Window when no dates are sent |
| `PRESENTATION_MAX_WINDOW_SECONDS` | `604800` | Longest window (S3 limit) |

## Design decisions

- **A missing date is filled in** (start: now; end: start plus the
  default window) instead of failing, which the DCS did with a 500.
- **Local storage URLs do not expire**, which is one reason local
  storage is refused in production.

## Known limitations

- Stored presentations are not deleted after their window; add an S3
  lifecycle rule on the `presentations/` prefix.

## Testing

- `tests/features/wallet_storage/test_presentations.py`
