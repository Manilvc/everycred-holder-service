# everycred-holder-service

FastAPI service behind the EveryCRED holder wallet app. Global Python
rules in `~/.claude/CLAUDE.md` apply; this file adds what is specific to
this repo.

## Commands

- `uv run pytest` — tests
- `uv run ruff check . && uv run ruff format .` — lint and format
- `uv run fastapi dev --port 8040` — local server
- `uv run python -m app.worker` — notification delivery worker
- `uv run alembic upgrade head` — apply migrations
- `uv run alembic revision --autogenerate -m "<change>"` — new migration
- `uv run alembic check` — confirm models and migrations match

Use `uv add <package>` to add dependencies; never edit the dependency
list by hand.

## Structure

Read `docs/README.md` before adding code. In short:

- New features go in `app/features/<feature_name>/` and are registered
  in `app/api/router.py`.
- Reuse what `app/core/` provides: `DbSession`, `Storage`, `Mailer`,
  `Connector`, `AppError` subclasses, `get_settings()`. Do not create new
  engines, HTTP clients, or settings readers.
- Holder routes depend on `CurrentHolder` (or `CurrentAuth` when the
  session is needed) from `app/features/auth/dependencies.py`.
- Services commit their own transactions (`await session.commit()`);
  audit entries are staged with `AuditRepository.record` in the same
  transaction.
- Shared resources are provided through lifespan state
  (`request.state`), not module globals.

## Data ownership

- This service owns holder identity only. Never store credential
  content, request data, or anything a DCS owns; fetch or forward it
  through `ConnectorClient` (`app/core/connector.py`).
- Path values forwarded to DCS use `ExternalId` / `SourceCode` from
  `app/shared/identifiers.py`.
- Keep `app/core/connector.py` and `app/core/signatures.py` in step with
  the connector service's contract.

## Database

- MySQL via `aiomysql`; its own database (`everycred_holder`), not the
  DCS database.
- Models use `UUIDPrimaryKeyMixin`, `TimestampMixin`, and `UTCDateTime`
  from `app/core/models.py`. Always use `utc_now()`.
- Import new models modules in `migrations/env.py` and
  `tests/conftest.py`. Generated migrations must not import `app` code.
- No queries inside loops; fetch in bulk (see
  `NotificationDeliveryService.deliver_due`).

## Security

- Never log emails, names, tokens, OTP codes, or credential content; log
  ids.
- Login, OTP, and reset responses must not reveal whether an email is
  registered.
- Never accept private key material; `PublicJwk` rejects it.
