# Holder profile

> Package: `app/features/holders/`
> Last updated: 2026-10-30

## Overview

The `holders` table and the signed-in holder's profile, served at the
DCS paths and in the DCS shape the wallet app stores as its user
profile.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| GET | `/v1/holder` | Get my profile | bearer |
| PUT | `/v1/holder/update` | Update name, contact, profile image | bearer |

### `GET /v1/holder`

Response `200` "Holder retrieved successfully!":

```json
{
  "id": 3141592653589793,
  "uuid": "00000000-0000-0000-0000-000000000000",
  "digi_client_id": null,
  "name": "Test Holder",
  "email": "holder@example.com",
  "profile_image": null,
  "login_type": "register",
  "did": "did:evrc:holder:00000000-0000-0000-0000-000000000000",
  "qrcode_path": "holders/<uuid>/did/qr-code.png",
  "holder_profile_path": "holders/<uuid>/did/profile.json",
  "is_kyc": false,
  "is_terms_accepted": false,
  "status": "registered",
  "created_at": "2026-10-22T10:00:00",
  "updated_at": "2026-10-22T10:00:00",
  "deleted_at": null,
  "contact": null
}
```

`id` is the integer the app later sends as `holder_id`.
`profile_image` is an absolute URL (presigned on S3) or null.

### `PUT /v1/holder/update`

Request `{"name"?, "contact"?, "profile_image"?}`, unknown fields
rejected. `profile_image` is raw base64 (no `data:` prefix) of a PNG,
JPEG or WebP up to `MAX_PROFILE_IMAGE_BYTES`. Response `200` "Your
handler profile is updated successfully." (the DCS wording) with the
profile, `contact` named `phone_number`.

| Status | `message` | When |
|--------|-----------|------|
| 422 | Image format not supported… | Not base64, wrong type, or too large |
| 422 | `<field> <reason>` | Validation failure |

## Flow

`HolderProfileService.build_detail` builds the DCS shape;
`update_profile` applies changes, stores a new image under
`holders/<uuid>/profile-image.<ext>`, and rewrites the public DID
profile document with the name and the image. When the name or contact
number changed, it queues a `holder.profile_updated` report so every
linked DCS shows the new values on its issuer screens (see
[onboarding](onboarding.md)).

## Data model

`holders`: `id` (UUID), `numeric_id` (random integer below 2^52,
unique), `email` (lower-cased, unique), `did` (unique), `full_name`,
`mobile`, `password_hash`, lockout fields, storage keys, `deleted_at`.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `MAX_PROFILE_IMAGE_BYTES` | `2097152` | Largest decoded profile image |

## Design decisions

- **Random integer ids.** The app needs an integer `id`; a random value
  below 2^52 is JavaScript-safe and does not reveal how many holders
  exist. `HolderRepository.pick_unused_numeric_id` checks candidates in
  one query.
- **The phone number stays out of the public profile document**, which
  the DCS published.
- **The document is rewritten only with a new image**, because the old
  image is not kept in a form it can embed.

## Known limitations

- Changing only the name does not update the public profile document.

## Testing

- `tests/features/holders/test_profile.py`
