# Credentials

> Package: `app/features/credentials/`
> Owner: EveryCRED backend team
> Last updated: 2026-10-21

## Overview

The holder's credentials, fetched live through the EveryCRED connector
from the DCS that issued them. Nothing about a credential is stored
here ("Fetch DID and Credentials (No Data Storage)" in the
architecture). Sharing, downloading, and emailing are audited by id.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| GET | `/v1/credentials` | List my credentials from every source | bearer |
| GET | `/v1/credentials/{credential_id}` | Get one | bearer |
| GET | `/v1/credentials/{credential_id}/share` | Share link and QR code | bearer |
| GET | `/v1/credentials/{credential_id}/download` | W3C credential JSON as a download | bearer |
| POST | `/v1/credentials/{credential_id}/email` | Email the link to someone | bearer |
| GET | `/v1/sources/{source_code}/credentials/{credential_id}/stats` | Verification statistics | bearer |

`GET /v1/credentials/{credential_id}` returns the connector's
`NormalizedCredential`:

```json
{
  "credential_id": "cred-1",
  "source_code": "dcs-india",
  "status": "issued",
  "title": "Example Degree",
  "holder_name": "Example Holder",
  "issuer": {"name": "Example University", "did": "did:evrc:issuer:...", "email": null, "logo_url": null, "description": null},
  "issued_at": "2026-01-01T00:00:00Z",
  "fields": {"grade": "A"},
  "credential_url": "https://dcs.example.com/...",
  "image_url": null,
  "qr_code_url": "https://dcs.example.com/...",
  "hash": "<hash>",
  "credential_json": {"@context": ["..."]}
}
```

`POST .../email` body: `{"recipient_email": "verifier@example.com", "note": "optional, up to 500 characters"}`.

Errors:

| Status | `error.code` | When |
|--------|--------------|------|
| 400 | `credential_not_shareable` | Source returned no public link |
| 404 | `not_found` | Not the holder's credential, or unknown |
| 404 | `credential_document_unavailable` | Download without a credential JSON |
| 429 | `too_many_requests` | Email limit per hour reached |
| 502 | `external_service_error` | Connector or SMTP unavailable |

## Flow

Every call goes through `ConnectorClient` with the holder's email; the
connector checks ownership. See [core/connector](../core/connector.md).

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `CREDENTIAL_EMAIL_HOURLY_LIMIT` | `10` | Emails per holder per hour |

## Design decisions

- The email rate limit counts `credential_emailed` audit entries, so no
  extra table or Redis is needed.
- The recipient address is never stored or logged.

## Known limitations

- `GET /v1/credentials` makes one connector call that fans out to every
  source; a slow source slows the list (the connector bounds this).

## Testing

`tests/features/credentials/test_credentials.py`.
