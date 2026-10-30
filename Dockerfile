# Multi-stage build for the EveryCRED holder service.
#
# Dependencies are installed into a virtualenv in the builder stage and
# only that virtualenv reaches the runtime image: no compiler, no uv, and no
# build cache in production. Mirrors the audit service's image layout.

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS builder

# uv is copied from its own image at a pinned version (the same pin the
# audit service uses) instead of being installed from the package index.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

# The virtualenv is built at the same path it runs from. Its scripts
# (uvicorn, alembic) hard-code the interpreter path in their first line,
# so a venv built in /build and copied to /app fails with "not found".
WORKDIR /app

# Manifests first so the slow dependency layer is rebuilt only when they
# change. --frozen fails the build if uv.lock and pyproject.toml disagree,
# so the image always has exactly the versions that were tested.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

# /run/mysqld is where docker-compose.mysql-socket.yml mounts the host's
# MySQL socket. It is created here because the root filesystem is
# read-only at run time.
RUN groupadd --gid 10001 holder \
 && useradd --uid 10001 --gid holder --no-create-home \
      --shell /usr/sbin/nologin holder \
 && mkdir -p /run/mysqld

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PORT=8041

WORKDIR /app

COPY --from=builder --chown=holder:holder /app/.venv /app/.venv
COPY --chown=holder:holder app ./app
# Migrations ship in the image so the container can bring the schema up
# to date by itself (`serve` and `migrate` in the entrypoint).
COPY --chown=holder:holder migrations ./migrations
COPY --chown=holder:holder alembic.ini pyproject.toml README.md ./
COPY --chown=holder:holder --chmod=0755 deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Non-root. The process writes nothing to disk: logs go to stdout, state
# lives in MySQL and the secret store.
USER 10001:10001

EXPOSE 8041

# The slim image has no curl; Python's standard library is enough. The
# start period covers the migrations `serve` applies first, which may
# wait up to DB_WAIT_SECONDS for the database.
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT', '8041')}/health/live\", timeout=3).status == 200 else 1)"]

# `serve` applies migrations and runs the API, `migrate` only applies
# them and exits, `worker` runs notification delivery.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]
