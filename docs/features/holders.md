# Holders

> Package: `app/features/holders/`
> Owner: EveryCRED backend team
> Last updated: 2026-10-21

## Overview

The `holders` table and the signed-in holder's profile: name, mobile,
profile image, and URLs of the DID QR code and DID profile document.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| GET | `/v1/holders/me` | Get my profile | bearer |
| PATCH | `/v1/holders/me` | Update name or mobile | bearer |
| PUT | `/v1/holders/me/profile-image` | Replace the profile image (multipart `image`) | bearer |

Response of all three:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "email": "holder@example.com",
  "did": "did:evrc:holder:00000000-0000-0000-0000-000000000000",
  "full_name": "Example Holder",
  "mobile": null,
  "profile_image_url": null,
  "did_qr_code_url": "https://files.example.com/...",
  "did_profile_url": "https://files.example.com/...",
  "created_at": "2026-10-21T10:00:00Z"
}
```

Errors:

| Status | `error.code` | When |
|--------|--------------|------|
| 413 | `payload_too_large` | Image over `MAX_PROFILE_IMAGE_BYTES` |
| 415 | `unsupported_image` | Bytes are not PNG, JPEG, or WebP |
| 422 | `validation_error` | Unknown field (e.g. `email`) or bad mobile number |

## Flow

`HolderProfileService.replace_profile_image` detects the type from the
file's magic bytes (`app/shared/uploads.py`), stores it at
`holders/<id>/profile-image.<ext>`, and records `profile_updated` in the
audit trail.

## Data model

`holders`: `email` (unique, lower-case), `did` (unique), `full_name`,
`mobile`, `password_hash`, `is_active`, `failed_login_count`,
`locked_until`, and the storage keys `profile_image_key`, `qr_code_key`,
`profile_document_key`.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `MAX_PROFILE_IMAGE_BYTES` | `2097152` | Upload limit |
| `STORAGE_URL_TTL_SECONDS` | `900` | Lifetime of returned URLs (S3) |

## Design decisions

- The email cannot be changed: it is the key DCS sources use to match
  credentials and requests to the holder.
- The declared content type is ignored; only the bytes decide.

## Known limitations

No account deletion endpoint yet.

## Testing

`tests/features/holders/test_profile.py`.
