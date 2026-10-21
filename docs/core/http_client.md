# `app/core/http_client.py`

> Last updated: 2026-10-21

## Purpose

Provide one pooled `httpx.AsyncClient` for all outbound calls: the
connector (every credential read goes through it) and, in the worker,
FCM. Creating a client per call throws away connection reuse and TLS
session caching.

## Public API

### `HttpClient`

`Annotated[httpx.AsyncClient, Depends(get_http_client)]`. Inject it
into clients through a dependency. `app/core/connector.py` reads it from
`request.state.http_client` directly in `get_connector_client`.

### `create_http_client(settings) -> httpx.AsyncClient`

Called once by the lifespan in `app.main` and once by `app.worker`.

## How it works

1. **Timeouts** — every request gets `HTTP_TIMEOUT_SECONDS` for connect,
   read, write, and pool acquisition. Override per call when a callee
   needs longer; `ConnectorClient` passes `CONNECTOR_TIMEOUT_SECONDS`.
2. **Pool limits** — `HTTP_MAX_CONNECTIONS` caps concurrent sockets so a
   slow upstream cannot exhaust file descriptors.
3. **Redirects** — disabled. A redirected API call could forward an
   `X-API-Key` or `Authorization` header to an unintended host.
4. **Tracing** — the `_forward_request_id` event hook adds
   `X-Request-ID` to every outbound request, so the connector's logs
   can be matched with ours.
5. **User-Agent** — `<service_name>/<service_version>`.
6. **Shutdown** — the lifespan calls `aclose()`.

## Failure modes

httpx raises `httpx.TimeoutException`, `httpx.ConnectError`, or
`httpx.HTTPStatusError` (after `response.raise_for_status()`). Callers
such as `ConnectorClient` catch these, log them, and raise
`ExternalServiceError` with a message that is safe to show clients.

## Changing this module

- Put callee-specific headers and base URLs in the caller (for example
  `ConnectorClient`), not in the shared client.
- Retries are not built in. Add them per caller, only for idempotent
  requests, with a bounded count and backoff.
