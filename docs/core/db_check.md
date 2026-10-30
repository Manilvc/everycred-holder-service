# `app/core/db_check.py`

> Last updated: 2026-10-29

## Purpose

Run before migrations (`python -m app.core.db_check`, called by the
container's `migrate` command, and by `serve` unless
`MIGRATE_ON_START=false`). It waits for the database and, on
failure, prints what went wrong and how to fix it instead of a driver
traceback. Invalid settings are reported one line per problem, without
echoing values, because pydantic's own message would print secrets.

## Public API

- `main() -> int` — exit code 0 when the database answered, 1 otherwise.
- `load_settings() -> Settings | None` — settings, or None after
  printing why they are invalid.
- `wait_for_database(settings, wait_seconds) -> bool` — retries until
  the deadline.
- `explain(url, error) -> list[str]` — hints for common MySQL errors.

## How it works

1. Load settings; on `ValidationError`, print field names and reasons.
2. Connect with a `NullPool` engine and run `SELECT 1`, retrying every
   2 seconds until `DB_WAIT_SECONDS` (default 30) pass.
3. On final failure, print the target (password hidden), the driver
   error, and hints from `explain`.

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `DB_WAIT_SECONDS` | `30` | How long to retry |
| `DATABASE_URL` | required | Database to check |

## Failure modes

Never raises; returns exit code 1.

## Tests

`tests/core/test_db_check.py`.
