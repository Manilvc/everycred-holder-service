# `app/core/email.py`

> Last updated: 2026-10-21

## Purpose

Send the service's emails: registration codes, password reset links,
and credential links shared by holders.

## Public API

- `OutgoingEmail(recipient, subject, body)` — a plain-text message.
- `EmailSender` (protocol) — `await send(email)`; raises
  `EmailDeliveryError` on failure.
- `SmtpEmailSender` — SMTP relay with STARTTLS and login.
- `ConsoleEmailSender` — local development; sends nothing and logs only
  that an email would have been sent.
- `create_email_sender(settings)` and the `Mailer` dependency.

```python
await mailer.send(
    OutgoingEmail(recipient=email, subject="Your code", body=body)
)
```

## How it works

1. `smtplib` is blocking, so `SmtpEmailSender._send_message` runs in a
   thread with `SMTP_TIMEOUT_SECONDS`.
2. STARTTLS uses `ssl.create_default_context()`, which verifies the
   relay's certificate.
3. On failure only the exception type is logged; its text can contain
   the recipient address.
4. The console backend never logs subject, body, or recipient: bodies
   contain OTP codes and reset links.

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `EMAIL_BACKEND` | `console` | `smtp` is required in production |
| `EMAIL_FROM` | `no-reply@example.com` | Sender address |
| `SMTP_HOST`, `SMTP_PORT` | —, `587` | Relay |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | — | Login (optional) |
| `SMTP_USE_STARTTLS` | `true` | Upgrade to TLS |
| `SMTP_TIMEOUT_SECONDS` | `10` | Connect and command timeout |

## Failure modes

| Situation | Behaviour | Logged as |
|-----------|-----------|-----------|
| Relay unreachable or refuses | `EmailDeliveryError`; services turn it into `ExternalServiceError` (502), except password reset, which only logs | `ERROR` |

## Changing this module

Keep messages plain text, or add an HTML part alongside it; never put
secrets in subjects.

## Tests

Tests replace the sender with `RecordingMailer` in `tests/conftest.py`
and read the codes and links it captured.
