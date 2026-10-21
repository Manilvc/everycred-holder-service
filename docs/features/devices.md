# Devices

> Package: `app/features/devices/`
> Owner: EveryCRED backend team
> Last updated: 2026-10-21

## Overview

FCM registration tokens of wallet installs, used by the worker to send
push notifications.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| PUT | `/v1/holders/me/push-token` | Register this device | bearer |
| DELETE | `/v1/holders/me/push-token` | Turn off pushes on this device | bearer |

`PUT` body:

```json
{"token": "<fcm registration token>", "platform": "android"}
```

`platform` is `android`, `ios`, or `web`. Response:
`{"platform": "android", "is_active": true}`.

## Flow

The token is bound to the session of the request. Logging out, changing
the password (other sessions), or resetting it deactivates the tokens of
the ended sessions. A token already registered (same device, perhaps
another holder) is moved to the current holder and session instead of
duplicated. The worker deactivates tokens FCM reports as `UNREGISTERED`.

## Data model

`push_tokens`: `holder_id`, `session_id`, `token` (unique), `platform`,
`is_active`.

## Design decisions

Binding to the session (not only the holder) means a shared or sold
device stops receiving the previous holder's notifications as soon as
they sign out.

## Testing

`tests/features/devices/test_push_tokens.py`.
