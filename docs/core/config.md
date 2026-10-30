# `app/core/config.py`

> Last updated: 2026-10-21

## Purpose

Hold every setting the service reads, parsed and validated once at
startup. Other modules call `get_settings()` (or inject `SettingsDep`)
instead of reading `os.environ`, so configuration lives in one place and
tests can override it.

## Public API

### `Settings`

A `pydantic_settings.BaseSettings` model. Values come from environment
variables (case-insensitive) and, locally, from `.env`. Real environment
variables win over `.env`. Secrets are `SecretStr`, so they never show in
logs or reprs; call `.get_secret_value()` only where the value is used.

### `get_settings() -> Settings`

Cached with `lru_cache`, so the environment is parsed once per process.
Tests that change environment variables call `get_settings.cache_clear()`;
tests that change one value use `monkeypatch.setattr(get_settings(), ...)`.

### `SettingsDep`

`Annotated[Settings, Depends(get_settings)]` for routes and dependency
providers.

### `Environment`, `StorageBackend`, `EmailBackend`

String enums for the matching settings.

## How it works

1. Pydantic parses and type-checks each field; constraints (`ge`, `le`,
   `min_length`, `pattern`) reject out-of-range values at startup.
2. Model validators check combinations:
   - `check_storage`: `STORAGE_BACKEND=s3` needs `AWS_REGION` and
     `S3_BUCKET`; production must use S3 (read-only containers, several
     replicas).
   - `check_email`: production must use SMTP; SMTP needs `SMTP_HOST`.
   - `check_urls`: `CONNECTOR_BASE_URL` is http(s),
     `PASSWORD_RESET_URL` contains `{token}`, and the two FCM settings are
     set together.
3. `is_production` is used by `app.main` to keep API docs off in
   production regardless of `ENABLE_DOCS`.

## Configuration

See `.env.example` for every variable with a comment. Groups:

| Group | Variables |
|-------|-----------|
| Service | `SERVICE_NAME`, `ENVIRONMENT`, `LOG_LEVEL`, `LOG_JSON`, `ENABLE_DOCS`, `CORS_ALLOWED_ORIGINS` |
| Database | `DATABASE_URL`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_ECHO`, `DATABASE_POOL_RECYCLE_SECONDS` |
| HTTP | `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_CONNECTIONS` |
| Tokens | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `SESSION_LIFETIME_DAYS`, `REGISTRATION_TOKEN_MINUTES` (time to register after OTP verification), `TOKEN_HASH_SECRET`, `RECOVERY_TOKEN_TTL_SECONDS` (120) |
| OTP and sign-in | `OTP_TTL_MINUTES` (2), `OTP_MAX_ATTEMPTS` (3), `OTP_RESEND_COOLDOWN_SECONDS`, `LOGIN_MAX_FAILED_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES`, `PASSWORD_RESET_TTL_MINUTES` (15), `PASSWORD_RESET_URL`, `ACCOUNT_DELETION_GRACE_DAYS` (30) |
| Wallet compatibility | `VERIFIER_BASE_URL` (prefix of share links; must be http(s)), `MAX_SHARE_RECIPIENTS` (10, recipients per "email this credential" call) |
| Google sign-in | `GOOGLE_CLIENT_IDS` (JSON list of OAuth client ids whose ID tokens `/holder/login/sso` accepts; empty disables it) |
| Email verification | `EMAIL_VERIFICATION_URL` (must contain `{token}`), `EMAIL_VERIFICATION_TTL_MINUTES` (60) |
| Connector | `CONNECTOR_BASE_URL`, `CONNECTOR_API_KEY`, `CONNECTOR_WEBHOOK_SECRET`, `CONNECTOR_TIMEOUT_SECONDS`, `WEBHOOK_TOLERANCE_SECONDS` |
| DIDs | `DID_PREFIX`, `MAX_KEYS_PER_HOLDER` |
| Storage | `STORAGE_BACKEND`, `STORAGE_LOCAL_DIR`, `STORAGE_PUBLIC_BASE_URL`, `STORAGE_URL_TTL_SECONDS`, `AWS_REGION`, `S3_BUCKET`, `S3_PREFIX`, `MAX_PROFILE_IMAGE_BYTES`, `MAX_PRESENTATION_BYTES`, `PRESENTATION_DEFAULT_WINDOW_SECONDS` (300), `PRESENTATION_MAX_WINDOW_SECONDS` (604800) |
| Email | `EMAIL_BACKEND`, `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_STARTTLS`, `SMTP_TIMEOUT_SECONDS` |
| Notifications | `SOCKET_REDIS_URL`, `SOCKET_CHANNEL`, `SOCKET_EVENT`, `FCM_PROJECT_ID`, `FCM_SERVICE_ACCOUNT_JSON`, `NOTIFICATION_REDIRECT_BASE_URL`, `NOTIFICATION_MAX_ATTEMPTS`, `WORKER_INTERVAL_SECONDS` |

## Failure modes

| Situation | Behaviour |
|-----------|-----------|
| Missing required variable or invalid value | `pydantic.ValidationError` at import of `app.main`; the process does not start. `python -m app.core.db_check` prints one line per problem without echoing values. |
| Secret too short (`JWT_SECRET_KEY`, `TOKEN_HASH_SECRET`, `CONNECTOR_WEBHOOK_SECRET` under 32 characters) | Same as above. |

## Changing this module

- Add a field with a type, a safe default (or none if it must be set),
  and a comment explaining the why. Add it to `.env.example` and the
  table above.
- Rotating `JWT_SECRET_KEY` signs every holder out. Rotating
  `TOKEN_HASH_SECRET` invalidates outstanding OTPs and reset links only.
  Rotating `CONNECTOR_WEBHOOK_SECRET` must be done together with the
  connector's `HOLDER_SERVICE_WEBHOOK_SECRET`.

## Tests

Settings are prepared in `tests/conftest.py`; the startup checks are
exercised in `tests/core/test_db_check.py`.
