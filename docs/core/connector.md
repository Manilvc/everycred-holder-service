# `app/core/connector.py`

> Last updated: 2026-10-21

## Purpose

The holder service stores no credentials and owns no issuer data.
Credentials, credential requests, workflow steps, KYC sessions, and
DigiLocker flows live in the DCS instance that issued them; the
EveryCRED connector knows which one and forwards the call.
`ConnectorClient` is the only code that talks to the connector.

Every call carries the holder's email. The connector only returns data
the source DCS links to that email, which is how ownership is enforced.

## Public API

### `ConnectorClient(http_client, settings)`

- `lookup_credentials(holder_email) -> CredentialLookupResponse` —
  `POST /v1/holders/credentials/lookup`.
- `get_credential(holder_email, credential_id) -> NormalizedCredential`
  — `POST /v1/holders/credentials/get`; 404 if not the holder's.
- `get_public_credential(credential_id) -> NormalizedCredential` —
  `GET /v1/credentials/{id}`, for the public verifier lookup.
- `record_verification(credential_id, body) -> OperationResult` —
  `POST /v1/credentials/{id}/verification-analytics`.
- `run_operation(holder_email, operation, *, source_code=None,
  params=None, body=None) -> OperationResponse` —
  `POST /v1/holders/operations`. `source_code=None` fans out to every
  source of the holder (list operations only).

```python
result = await connector.run_operation(
    holder.email,
    "requests.get",
    source_code="dcs-india",
    params={"request_id": "req-1"},
)
```

### `Connector`

`Annotated[ConnectorClient, Depends(get_connector_client)]`.

### Response models

`NormalizedCredential`, `CredentialIssuer`, `CredentialLookupItem`,
`CredentialLookupResponse`, `OperationResult`, `OperationResponse` —
the connector's contract, validated on every response.
`NormalizedCredential` includes `credential_unique_id`, `subject_name`,
`subject_logo_url`, `valid_from`, `valid_until` and
`credential_json_content` (the original document string);
`CredentialLookupItem` includes `first_seen_at` and
`status_changed_at`.

## How it works

1. `_request` sends JSON with `X-API-Key: CONNECTOR_API_KEY` and
   `CONNECTOR_TIMEOUT_SECONDS`; the shared client adds `X-Request-ID`.
2. Errors use the envelope `{"error": {"code", "message"}}` and are
   mapped by `_error_for`:

   | Connector status | Raised | Client sees |
   |------------------|--------|-------------|
   | 404 | `NotFoundError` | 404 |
   | 400, 422 | `UpstreamRejectedError` | 400 with the connector's `error.message` |
   | other, timeout, network | `ExternalServiceError` | 502 |

3. `_parse` validates the body against the expected model; an
   unexpected shape is a 502, never a half-parsed object.

Operations the connector accepts: `requests.list`, `requests.get`,
`requests.fields`, `requests.submit`, `requests.decline`, `kyc.detail`,
`workflow.list`, `workflow.get`, `workflow.consent`,
`workflow.node_submit`, `workflow.node_accept`, `workflow.node_decline`,
`integrations.list`, `integrations.start`, `integrations.inputs`,
`integrations.cancel`, `digilocker.initialize`, `digilocker.complete`,
`credentials.stats`. Parameter values must match
`^[A-Za-z0-9._:-]{1,128}$` (enforced on our routes by
`app/shared/identifiers.py`).

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `CONNECTOR_BASE_URL` | required | Connector root URL |
| `CONNECTOR_API_KEY` | required | Key of a connector client of kind `holder_service` |
| `CONNECTOR_TIMEOUT_SECONDS` | `15` | Per-call timeout |

## Failure modes

| Situation | Behaviour | Logged as |
|-----------|-----------|-----------|
| Timeout or network error | 502 `external_service_error` | `WARNING` |
| Connector 5xx | 502 | `ERROR` with status and code |
| Unexpected response shape | 502 | `ERROR` with the model name |

## Changing this module

- Keep the models in step with the connector's contract; both repos
  change together.
- Never log the holder email or response bodies.

## Tests

Feature tests replace the client's transport with `httpx.MockTransport`
(`FakeConnector` in `tests/conftest.py`):
`tests/features/credentials/` and `tests/features/gateway/`.
