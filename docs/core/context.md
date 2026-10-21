# `app/core/context.py`

> Last updated: 2026-10-21

## Purpose

Hold per-request values (today only the request id) in a `ContextVar`,
so logging and the outbound HTTP client can read them without passing
them through every function.

## Public API

- `REQUEST_ID_HEADER` — `"X-Request-ID"`.
- `request_id_context` — the `ContextVar`; set and reset by
  `RequestContextMiddleware`.
- `get_request_id() -> str | None` — the current id, or None outside a
  request (for example in the worker).

## How it works

Context variables are copied into tasks created from the request, so
concurrent requests never see each other's id.

## Changing this module

Add new per-request values here as further `ContextVar`s, set them in
the middleware, and read them through a getter.

## Tests

`tests/core/test_middleware.py`.
