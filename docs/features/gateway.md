# Gateway

> Package: `app/features/gateway/`
> Owner: EveryCRED backend team
> Last updated: 2026-10-21

## Overview

The issuer-side actions the wallet performs today against DCS: credential
requests, KYC details, workflow-engine participant steps, integration
KYC sessions, and DigiLocker. Their data stays in the DCS; each route
adds the signed-in holder's email and forwards the action through the
connector, which calls the right DCS source.

## Endpoints

All require a bearer token and return `OperationResponse`.

| Method | Path | Operation | Replaces (DCS) |
|--------|------|-----------|----------------|
| GET | `/v1/requests` | `requests.list` (all sources) | `GET /v1/holder/subject/requests` |
| GET | `/v1/sources/{source}/requests/{request_id}` | `requests.get` | `GET /v1/holder/request/{request_id}` |
| GET | `/v1/sources/{source}/requests/{request_id}/fields` | `requests.fields` | `GET /v1/wallet/holder/subject/request/fields` |
| POST | `/v1/sources/{source}/requests/{request_id}/submission` | `requests.submit` | `POST /v1/holder/request/submission` |
| POST | `/v1/sources/{source}/requests/{request_id}/decline` | `requests.decline` | `POST /v1/wallet/holder/subject/request/defuse` |
| GET | `/v1/sources/{source}/kyc-detail` | `kyc.detail` | `GET /v1/wallet/holder/request/kyc-detail` |
| GET | `/v1/workflow-requests` | `workflow.list` (all sources) | `GET /v1/workflow-engine/holder/requests` |
| GET | `/v1/sources/{source}/workflow-requests/{request_uuid}` | `workflow.get` | `GET .../requests/{request_uuid}` |
| POST | `.../workflow-requests/{request_uuid}/consent` | `workflow.consent` | `POST .../{request_uuid}/consent` |
| POST | `.../workflow-requests/{request_uuid}/nodes/{node_key}/submit` | `workflow.node_submit` | `POST .../nodes/{node_key}/submit` |
| POST | `.../nodes/{node_key}/accept` | `workflow.node_accept` | `POST .../nodes/{node_key}/accept` |
| POST | `.../nodes/{node_key}/decline` | `workflow.node_decline` | `POST .../nodes/{node_key}/decline` |
| GET | `/v1/sources/{source}/requests/{request_id}/integrations` | `integrations.list` | `GET /v1/holder/request/{request_id}/integration` |
| POST | `.../integrations/{type}/{tool_code}/{flow}/start` | `integrations.start` | `POST .../{type}/{tool}/{flow}/start` |
| POST | `.../integrations/{type}/{tool_code}/{flow}/inputs` | `integrations.inputs` | `POST .../inputs` |
| POST | `.../integrations/{type}/{tool_code}/{flow}/cancel` | `integrations.cancel` | `POST .../cancel` |
| POST | `/v1/sources/{source}/digilocker/initialize` | `digilocker.initialize` | `POST /v1/sure-pass/digilocker/initialize` |
| GET | `/v1/sources/{source}/digilocker/complete-flow/{client_id}` | `digilocker.complete` | `GET /v1/sure-pass/complete-flow/{client_id}` |

Response:

```json
{
  "items": [
    {
      "source_code": "dcs-india",
      "status_code": 200,
      "ok": true,
      "data": {"...": "the source's data"},
      "message": null
    }
  ]
}
```

List routes return one item per source; a failing source appears with
`ok: false` without failing the others. POST bodies are passed to the
source unchanged.

Errors:

Errors use the DCS envelope `{"status", "data", "message"}`.

| Status | `message` | When |
|--------|-----------|------|
| 400 | The connector's message | Connector rejected the call (unknown operation, missing source, invalid params) |
| 404 | The connector's message | Unknown source for this holder |
| 422 | `<field> <reason>` | A path value outside `^[A-Za-z0-9._:-]{1,128}$` |
| 502 | The credential network is unavailable. | Connector unavailable |

The wallet app's DCS paths are also served, in the DCS envelope and
shapes rather than one item per source (`wallet_router.py`):

| Method | Path | Operation(s) |
|---|---|---|
| GET | `/v1/holder/subject/requests?page&size&search` (deprecated `/v1/subject/requests`, unpaged) | `requests.list`, merged across sources, newest first, `source_code` on each item |
| GET | `/v1/holder/request/{request_id}` (deprecated `/v1/request/{request_id}`) | `requests.find` (all sources); the one that has it answers |
| POST | `/v1/holder/request/submission` (deprecated `/v1/request/submission`) | `requests.find`, then `requests.submit` at that source |

A source that fails a list is left out and logged. If a request id is
found in more than one source, the first is used and a warning logged.

## Design decisions

- Path values are validated before forwarding (`app/shared/identifiers.py`)
  so they cannot alter the URL the connector builds.
- Thin routes on purpose: business rules for requests and workflows stay
  in DCS, which owns the data.

## Known limitations

- DCS answers these calls on its internal holder API
  (`/v1/internal/holder/*` in everycred-backend, see its
  `docs/connector_integration.md`), which acts for a holder email sent
  by the connector instead of a DCS holder JWT.
- The connector forwards no query string, so DCS lists return their
  first 100 items per source.
- The DigiLocker wallet callback (`GET /v1/sure-pass/digilocker/wallet-callback`)
  and integration callback stay on DCS; they are browser redirects.

## Testing

`tests/features/gateway/test_gateway.py` and
`tests/features/gateway/test_wallet_requests.py`.
