"""Background worker: sends queued notifications and registration reports.

Run one instance per deployment::

    python -m app.worker

Every ``WORKER_INTERVAL_SECONDS`` it sends the notification deliveries
that are due over socket and push, and reports new registrations to DCS
sources through the connector, retrying failures with backoff.

After each successful round it touches :data:`HEARTBEAT_FILE`; the
container health check (``python -m app.worker --check``) reports
unhealthy when the file is older than :data:`HEARTBEAT_MAX_AGE_SECONDS`,
for example because the database has been unreachable for a while.

Deliveries are not locked between processes, so running two workers at
once could send a notification or a report twice.
"""

import asyncio
import logging
import signal
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.connector import ConnectorClient
from app.core.database import create_database_engine, create_session_factory
from app.core.http_client import create_http_client
from app.core.logging import configure_logging
from app.features.notifications.channels import (
    PushSender,
    RedisSocketPublisher,
    SocketPublisher,
    create_push_sender,
    create_socket_publisher,
)
from app.features.notifications.service import NotificationDeliveryService
from app.features.onboarding.service import RegistrationReportService

logger = logging.getLogger("app.worker")

BATCH_SIZE = 100
# /tmp is the only writable path in the read-only container.
HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "everycred-holder-heartbeat"
HEARTBEAT_MAX_AGE_SECONDS = 120


async def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    socket_publisher: SocketPublisher | None,
    push_sender: PushSender | None,
    connector: ConnectorClient,
) -> int:
    """Send one batch of deliveries and reports; return how many ran."""
    async with session_factory() as session:
        delivery_service = NotificationDeliveryService(
            session, settings, socket_publisher, push_sender
        )
        delivered = await delivery_service.deliver_due(BATCH_SIZE)
    async with session_factory() as session:
        report_service = RegistrationReportService(
            session, settings, connector
        )
        reported = await report_service.deliver_due(BATCH_SIZE)
    return delivered + reported


async def run_forever(stop: asyncio.Event) -> None:
    """Loop until ``stop`` is set, logging (not raising) failed rounds."""
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    http_client = create_http_client(settings)
    socket_publisher = create_socket_publisher(settings)
    push_sender = create_push_sender(settings, http_client)
    connector = ConnectorClient(http_client, settings)
    logger.info(
        "Worker started; socket %s, push %s, every %s s",
        "on" if socket_publisher else "off",
        "on" if push_sender else "off",
        settings.worker_interval_seconds,
    )
    try:
        while not stop.is_set():
            try:
                sent = await run_once(
                    session_factory,
                    settings,
                    socket_publisher,
                    push_sender,
                    connector,
                )
                HEARTBEAT_FILE.touch()
                if sent:
                    logger.info(
                        "Worker round: %s deliveries and reports", sent
                    )
            except Exception:
                # A database or network blip must not kill the worker;
                # the next round tries again.
                logger.exception("Worker round failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.worker_interval_seconds
                )
    finally:
        if isinstance(socket_publisher, RedisSocketPublisher):
            await socket_publisher.client.aclose()
        await http_client.aclose()
        await engine.dispose()
        logger.info("Worker stopped")


def is_healthy(now: float | None = None) -> bool:
    """Return True if a round succeeded within the allowed age."""
    try:
        last_round = HEARTBEAT_FILE.stat().st_mtime
    except FileNotFoundError:
        return False
    current = time.time() if now is None else now
    return current - last_round <= HEARTBEAT_MAX_AGE_SECONDS


def main() -> None:
    """Entry point: configure logging and stop cleanly on SIGTERM.

    With ``--check``, exit 0 or 1 by :func:`is_healthy` instead; used by
    the container health check.
    """
    if "--check" in sys.argv[1:]:
        sys.exit(0 if is_healthy() else 1)
    settings = get_settings()
    configure_logging(settings.log_level, use_json=settings.log_json)

    async def runner() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            # Not supported on Windows event loops; Ctrl+C still works
            # there through KeyboardInterrupt.
            with suppress(NotImplementedError):
                loop.add_signal_handler(signal_number, stop.set)
        await run_forever(stop)

    with suppress(KeyboardInterrupt):
        asyncio.run(runner())


if __name__ == "__main__":
    main()
