# Audit

> Package: `app/features/audit/`
> Owner: EveryCRED backend team
> Last updated: 2026-10-21

## Overview

A record of security-relevant holder actions, shown to the holder as
account activity and used for the credential email rate limit.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| GET | `/v1/holders/me/audit-logs?limit&offset` | List my activity | bearer |

```json
{
  "items": [
    {
      "action": "credential_shared",
      "resource_type": "credential",
      "resource_id": "dcs-india:cred-1",
      "created_at": "2026-10-21T10:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

Actions: `registered`, `login_succeeded`, `login_failed`, `logged_out`,
`password_changed`, `password_reset`, `profile_updated`,
`key_registered`, `key_revoked`, `credential_shared`,
`credential_downloaded`, `credential_emailed`, `presentation_stored`.

## Flow

Services call `AuditRepository.record(...)` in the same transaction as
the change they describe, so an action is recorded if and only if it
happened.

## Data model

`holder_audit_logs`: `holder_id`, `action`, `resource_type`,
`resource_id`, `created_at`; index on `(holder_id, action, created_at)`.

## Design decisions

Entries hold ids only, never personal data (no recipient emails, no IP
addresses).

## Testing

`tests/features/auth/test_auth.py::test_audit_log_records_sign_ins`.
