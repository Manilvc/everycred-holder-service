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

| Status | `error.code` | When |
|--------|--------------|------|
| 400 | connector code (`unknown_operation`, `source_required`, `invalid_params`) | Connector rejected the call |
| 404 | `not_found` | Unknown source for this holder |
| 422 | `validation_error` | A path value outside `^[A-Za-z0-9._:-]{1,128}$` |
| 502 | `external_service_error` | Connector unavailable |

## Design decisions

- Path values are validated before forwarding (`app/shared/identifiers.py`)
  so they cannot alter the URL the connector builds.
- Thin routes on purpose: business rules for requests and workflows stay
  in DCS, which owns the data.

## Known limitations

- DCS must accept these calls from the connector on behalf of a holder
  email (service-to-service), instead of a DCS holder JWT. That DCS-side
  endpoint set does not exist yet.
- The DigiLocker wallet callback (`GET /v1/sure-pass/digilocker/wallet-callback`)
  and integration callback stay on DCS; they are browser redirects.

## Testing

`tests/features/gateway/test_gateway.py`.
