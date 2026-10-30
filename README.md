# everycred-holder-service

API behind the EveryCRED holder wallet app. It owns holder accounts,
sessions, DIDs and device public keys, push tokens, the notification
inbox, and stored presentations. Credentials, credential requests, and
workflow steps stay in the DCS that issued them; this service reads and
forwards them through the EveryCRED connector service and stores none of
their content.

The routes the wallet app calls keep the DCS backend's paths, request
bodies, status codes, messages and `{status, data, message}` envelope,
so the app only points `EXPO_PUBLIC_API_BASE_URL` at `<this host>/v1`.
See [docs/wallet_compatibility.md](docs/wallet_compatibility.md).

See [docs/README.md](docs/README.md) for the architecture and links to
every module and feature.

## Run locally

Requires Python 3.13, [uv](https://docs.astral.sh/uv/), MySQL or MariaDB,
and a running connector service.

```bash
cp .env.example .env            # then fill in the <placeholders>
uv sync
uv run alembic upgrade head
uv run fastapi dev --port 8040  # API at http://127.0.0.1:8040/docs
uv run python -m app.worker     # notification delivery, in a second shell
```

Create the database first:
`CREATE DATABASE everycred_holder CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`

## Tests and lint

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Tests use in-memory SQLite and fake storage, email, and connector; they
need no external services.

## Docker

```bash
docker compose build
docker compose up -d   # migrate, then api (127.0.0.1:8041) and worker
```

The image includes the Alembic migrations. Started on its own, the
container applies them before the API (`MIGRATE_ON_START`, default
`true`), so a plain `docker run` needs no separate migration step:

```bash
docker run -d --env-file .env -p 127.0.0.1:8041:8041 \
  -e ROOT_PATH=/holder -e FORWARDED_ALLOW_IPS="*" \
  --add-host host.docker.internal:host-gateway everycred-holder-service
```

`ROOT_PATH` must match the nginx location: without it the API still
answers, but `/docs` sends "Try it out" requests to `/v1/...` instead of
`/holder/v1/...`. `FORWARDED_ALLOW_IPS="*"` is safe only because the
port is published on 127.0.0.1, so nginx is the only caller.

Compose sets `MIGRATE_ON_START=false` for `api`, because its `migrate`
service runs them first, and sets `ROOT_PATH` and `FORWARDED_ALLOW_IPS`
itself.

`deploy/nginx/holder-subpath.conf` publishes it under `/holder/`.

## Environment

Every variable is listed with a comment in `.env.example` and
explained in [docs/core/config.md](docs/core/config.md). Required:
`DATABASE_URL`, `JWT_SECRET_KEY`, `TOKEN_HASH_SECRET`,
`CONNECTOR_BASE_URL`, `CONNECTOR_API_KEY`, `CONNECTOR_WEBHOOK_SECRET`.
Production also requires `STORAGE_BACKEND=s3` and `EMAIL_BACKEND=smtp`.
