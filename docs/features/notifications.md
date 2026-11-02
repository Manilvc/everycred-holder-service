# Notifications

> Package: `app/features/notifications/`
> Owner: EveryCRED backend team
> Last updated: 2026-10-28

## Overview

When a DCS issues or revokes a credential, a credential request
changes, or an issuer invites a holder, the connector sends a signed
webhook here. The service writes
an inbox entry and delivers it live over the EveryCRED Socket service
and FCM push. The wallet also reads and marks its inbox.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| GET | `/v1/notifications?limit&offset&unread_only` | List my inbox | bearer |
| POST | `/v1/notifications/{id}/read` | Mark one read | bearer |
| POST | `/v1/notifications/read-all` | Mark all read | bearer |
| POST | `/v1/connector/events` | Receive a connector event | HMAC signature |

### `POST /v1/connector/events`

Headers: `X-EveryCRED-Event`, `X-EveryCRED-Delivery` (idempotency key),
`X-EveryCRED-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "<t>.<body>">`.

```json
{
  "id": "evt_0001",
  "event": "credential.issued",
  "created_at": "2026-10-21T10:00:00Z",
  "data": {
    "source_code": "dcs-india",
    "holder_email": "holder@example.com",
    "credential_id": "cred-1",
    "request_id": null,
    "status": "issued"
  }
}
```

Response `202 Accepted`: `{"status": "accepted" | "duplicate" | "ignored"}`.
`ignored` means no holder has that email. A `holder.invited` event for
an email without an account is kept for sign-up instead and answered
`accepted` (see [onboarding](onboarding.md)).

`holder.invited` carries `source_code`, `holder_email` and an optional
`inviter_name` (up to 200 characters); `credential_id` and `request_id`
are null.

Errors:

Errors use the DCS envelope `{"status", "data", "message"}`.

| Status | `message` | When |
|--------|-----------|------|
| 400 | A valid delivery id is required. / The event body is invalid. | Signed, but the delivery id or body is unusable |
| 401 | The signature is invalid. | Missing, wrong, or stale signature |
| 413 | The request body must not exceed … bytes. | Body over 16 KB |

## Flow

```mermaid
sequenceDiagram
    participant DCS
    participant Connector
    participant API as holder service
    participant DB
    participant Worker
    participant Redis as Redis (Socket service)
    participant FCM
    DCS->>Connector: credential issued (webhook)
    Connector->>API: POST /v1/connector/events (signed)
    API->>DB: connector_events + inbox_notifications + 2 deliveries
    API-->>Connector: 202
    Worker->>DB: due deliveries
    Worker->>Redis: PUBLISH socketio_notifications
    Worker->>FCM: messages:send per active token
    Worker->>DB: delivered / retry / failed
```

Event to notification type (values match the DCS holder registry):

| Event | `data.status` | `notification_type` | Redirect |
|-------|---------------|---------------------|----------|
| `credential.issued` | — | `credential_issued` | `credential/<list id>` |
| `credential.revoked` | — | `credential_revoked` | `credential/<list id>` |
| `request.created` | — | `new_credential_request` | `request/<request_id>` |
| `request.updated` | `approved` | `credential_request_approved` | `request/<request_id>` |
| `request.updated` | `declined` | `credential_request_declined` | `request/<request_id>` |
| `request.updated` | other | `credential_request_updated` | `request/<request_id>` |
| `holder.invited` | — | `issuer_invitation` | none |

The socket message is the shape DCS publishes, so the existing Socket
service needs no change:
`{"event": "new_request", "data": <inbox payload>, "user_uuid": "<holder id>", "room": "user_<holder id>"}`.

The push is the one the DCS sent (`build_inbox_push_message` and
`fcm_client.build_fcm_message` there), so the wallet app's existing push
handling works unchanged (`to_push_data`, `FcmPushSender` in
`channels.py`):

- `notification` `{title, body}` from the inbox row; Android priority
  high with `notification.channel_id` = `FCM_ANDROID_CHANNEL_ID`; APNs
  priority 10, alert, default sound.
- `data` (all strings): `uuid`, `notification_type`, `redirect_module`,
  `redirect_path`, `redirect_entity_type`, `redirect_entity_id`; every
  scalar value of `extra_metadata` at the top level (`request_id`,
  `credential_id`, `source_code`); `type` = the notification type; and
  `category`: `issuer` for request types, `credential` for credential
  types, `general` otherwise. FCM-reserved keys (`from`, `notification`,
  `message_type`, `google*`, `gcm*`) and empty values are dropped.

A request push therefore carries `data.type = new_credential_request` and
`data.request_id`, which the app uses to open `request/<request_id>`.

For credential events `credential_id` is the credential's numeric id in the
holder's credential list (`CredentialRef.numeric_id`, created on the event
if the holder has not listed the credential yet): the app opens
`/(app)/credential/<id>` with it, as it did with the DCS numeric id. The
connector's id is kept as `credential_unique_id`.

A JSON setting that is not a JSON object (for example a file path)
stops the service at startup with a message naming
`FCM_SERVICE_ACCOUNT_FILE`; an unreadable key file stops the worker with a
message to mount it.

Retries: socket publish failures and retryable FCM errors (429, 5xx,
network) wait 30 s, 2 min, 10 min, 30 min, then hourly, up to
`NOTIFICATION_MAX_ATTEMPTS`. A channel that is not configured, or a
holder with no active device, marks the row `skipped`.

## Data model

| Table | Purpose |
|-------|---------|
| `inbox_notifications` | Inbox entries (DCS inbox payload fields) |
| `connector_events` | Received delivery ids (unique), event, source, holder id; no email |
| `notification_deliveries` | Outbox: channel, status, attempts, `next_attempt_at`, `last_error` |

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `CONNECTOR_WEBHOOK_SECRET` | required | Verifies event signatures |
| `WEBHOOK_TOLERANCE_SECONDS` | `300` | Replay window |
| `SOCKET_REDIS_URL` | unset (socket off) | Redis of the Socket service, with DB index, e.g. `redis://:<password>@redis:6379/2` |
| `SOCKET_CHANNEL` | `socketio_notifications` | Channel the Socket service subscribes to |
| `SOCKET_EVENT` | `new_request` | Socket.IO event the wallet listens for |
| `FCM_PROJECT_ID` | unset (push off) | Firebase project (the same project the app and the DCS used) |
| `FCM_SERVICE_ACCOUNT_JSON` | unset | The service account key JSON on one line, starting with `{` |
| `FCM_SERVICE_ACCOUNT_FILE` | unset | Or: path of the key file **inside the container**, e.g. `/run/secrets/firebase-sa.json` mounted by `docker-compose.fcm.yml` (see that file). Set the JSON or the file, not both |
| `FCM_ANDROID_CHANNEL_ID` | `requests` | Android notification channel; the wallet app's `defaultChannel` (expo-notifications in app.json) |
| `NOTIFICATION_REDIRECT_BASE_URL` | `everycredwallet://` | Deep link base |
| `NOTIFICATION_MAX_ATTEMPTS` | `8` | Attempts per delivery |
| `WORKER_INTERVAL_SECONDS` | `5` | Worker loop interval |

## Design decisions

- **Deleted accounts get no notifications.** An event for a holder whose
  account is deleted is recorded and answered `ignored`.
- **Outbox, not inline sends.** The webhook answers in milliseconds and
  a Redis or FCM outage never loses a notification.
- **Signature before parsing.** Nothing unauthenticated is interpreted.
- **No email stored for events**; only the resolved holder id.
- **Generic texts.** Events carry ids only; the wallet loads details.
  An invite names the inviting organisation, since there is nothing
  else to open.

## Known limitations

- The Socket service lets any client join any `user_<id>` room without
  authentication (DCS `Socket/asgi.py`). Holder ids are random UUIDs,
  but the Socket service should verify a holder token before joining.
- One worker instance only; deliveries are not locked across processes.

## Testing

`tests/features/notifications/test_connector_events.py` and
`tests/features/notifications/test_delivery.py`.
