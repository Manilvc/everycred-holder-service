#!/bin/sh
# Container entrypoint for the holder service.
#
#   serve    Apply Alembic migrations, then run the API with uvicorn
#            (default). MIGRATE_ON_START=false skips the migrations.
#   migrate  Wait for the database (explaining any failure in plain words),
#            apply Alembic migrations, then exit.
#   worker   Run the background worker: notification delivery over socket
#            and push. Run exactly one.
#   *        Run the given command as-is (for example `sh` when debugging).
#
# Settings for `serve`:
#   MIGRATE_ON_START Apply migrations before starting (default true), so a
#                    plain `docker run` of the image works on its own. The
#                    compose file sets it to false for `api` because its
#                    `migrate` service has already run them.
#   PORT            Port to listen on inside the container (default 8041).
#   ROOT_PATH        Public path prefix nginx strips, e.g. /holder, so
#                    generated URLs and the docs pages include it.
#   WEB_CONCURRENCY  Number of uvicorn worker processes (default 2).
#   FORWARDED_ALLOW_IPS
#                    Proxies trusted for X-Forwarded-* headers. The compose
#                    file publishes the port on 127.0.0.1 only, so the only
#                    caller is nginx on the host; "*" is safe there.
#
# Settings for `migrate` (and `serve` when it migrates):
#   DB_WAIT_SECONDS  How long to keep retrying the database (default 30).
set -eu

apply_migrations() {
    python -m app.core.db_check
    alembic upgrade head
}

case "${1:-serve}" in
    serve)
        # Migrate here, before uvicorn forks its workers, so the workers
        # never race each other on the same migration.
        if [ "${MIGRATE_ON_START:-true}" = "true" ]; then
            apply_migrations
        fi
        exec uvicorn app.main:app \
            --host 0.0.0.0 \
            --port "${PORT:-8041}" \
            --root-path "${ROOT_PATH:-}" \
            --workers "${WEB_CONCURRENCY:-2}" \
            --proxy-headers \
            --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
            --no-server-header \
            --timeout-graceful-shutdown 20
        ;;
    migrate)
        apply_migrations
        ;;
    worker)
        exec python -m app.worker
        ;;
    *)
        exec "$@"
        ;;
esac
