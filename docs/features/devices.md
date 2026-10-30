# Devices (push tokens)

> Package: `app/features/devices/`
> Last updated: 2026-10-22

## Overview

FCM registration tokens of wallet installs, at the DCS paths. A token
is bound to the session that registered it, so ending the session
(password change, reset, account deletion) stops pushes to that device.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| PUT | `/v1/push/holder/token` | Register or refresh this device | bearer |
| DELETE | `/v1/push/holder/token` | Turn off pushes for a token | bearer |

### `PUT /v1/push/holder/token`

Request:

```json
{ "token": "<fcm token>", "platform": "android", "device_label": "Pixel 8", "app_version": "2.3.0" }
```

Response `200` "Device registered for notifications." with
`{"uuid": "<token row id>", "platform": "android"}`.

### `DELETE /v1/push/holder/token`

Request `{"token": "<fcm token>"}`. `200` "Device unregistered from
notifications.", or `404` "This device isn't registered for
notifications." when the token is unknown or another holder's.

## Data model

`push_tokens`: `holder_id`, `session_id`, `token` (unique), `platform`,
`is_active`, `device_label`, `app_version`.

## Design decisions

- **One row per token.** A token signed in by another holder moves to
  them instead of both receiving pushes.
- **Unknown and foreign tokens look the same** on delete, so tokens
  cannot be probed.

## Testing

- `tests/features/devices/test_push_tokens.py`
