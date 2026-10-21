"""Outbound email: OTP codes, password reset links, shared credentials.

:class:`SmtpEmailSender` sends through an SMTP relay with STARTTLS.
:mod:`smtplib` is blocking, so each message is sent in a worker thread
with a timeout. :class:`ConsoleEmailSender` is for local development:
it sends nothing and logs only that an email would have been sent,
because the subject and body can hold codes and the recipient is
personal data.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Annotated, Protocol

from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from app.core.config import EmailBackend, Settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Raised when the SMTP relay refuses or cannot be reached."""


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """A plain-text email ready to send."""

    recipient: str
    subject: str
    body: str


class EmailSender(Protocol):
    """Interface shared by the email backends."""

    async def send(self, email: OutgoingEmail) -> None:
        """Send ``email`` or raise :class:`EmailDeliveryError`."""


class ConsoleEmailSender:
    """Logs that an email was sent, without its content. Development only."""

    async def send(self, email: OutgoingEmail) -> None:
        """Record the send without exposing the recipient or content."""
        logger.info("Console email backend: email not sent (dev only)")


class SmtpEmailSender:
    """Sends email through an SMTP relay using STARTTLS.

    Attributes:
        settings: Source of the relay address, credentials and sender.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send(self, email: OutgoingEmail) -> None:
        """Send ``email`` in a worker thread.

        Raises:
            EmailDeliveryError: The relay could not be reached or
                refused the message.
        """
        message = EmailMessage()
        message["From"] = str(self.settings.email_from)
        message["To"] = email.recipient
        message["Subject"] = email.subject
        message.set_content(email.body)
        try:
            await run_in_threadpool(self._send_message, message)
        except (smtplib.SMTPException, OSError) as exc:
            # The exception text can contain the recipient address.
            logger.error("SMTP delivery failed: %s", type(exc).__name__)
            raise EmailDeliveryError("The email could not be sent.") from exc

    def _send_message(self, message: EmailMessage) -> None:
        settings = self.settings
        with smtplib.SMTP(
            str(settings.smtp_host),
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        ) as smtp:
            if settings.smtp_use_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username and settings.smtp_password:
                smtp.login(
                    settings.smtp_username,
                    settings.smtp_password.get_secret_value(),
                )
            smtp.send_message(message)


def create_email_sender(settings: Settings) -> EmailSender:
    """Build the backend selected by ``EMAIL_BACKEND``."""
    if settings.email_backend is EmailBackend.SMTP:
        return SmtpEmailSender(settings)
    return ConsoleEmailSender()


def get_email_sender(request: Request) -> EmailSender:
    """Return the sender created during application startup."""
    return request.state.email_sender


Mailer = Annotated[EmailSender, Depends(get_email_sender)]
