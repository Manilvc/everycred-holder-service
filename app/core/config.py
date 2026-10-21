"""Service configuration loaded from environment variables.

Every setting the service reads lives on :class:`Settings`. Other modules
call :func:`get_settings` instead of reading ``os.environ`` directly, so
configuration stays in one place and can be overridden in tests.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends
from pydantic import EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Environment(StrEnum):
    """Deployment environments the service can run in."""

    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class StorageBackend(StrEnum):
    """Where holder files (images, QR codes, presentations) are stored."""

    S3 = "s3"
    LOCAL = "local"


class EmailBackend(StrEnum):
    """How emails (OTPs, reset links, shared credentials) are sent."""

    SMTP = "smtp"
    CONSOLE = "console"


class Settings(BaseSettings):
    """Runtime settings for the holder service.

    Values are read from environment variables (case-insensitive) and,
    for local development, from a ``.env`` file in the working
    directory. Real environment variables take precedence over ``.env``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "everycred-holder-service"
    service_version: str = "0.1.0"
    environment: Environment = Environment.LOCAL

    log_level: LogLevel = "INFO"
    log_json: bool = True

    enable_docs: bool = False
    cors_allowed_origins: list[str] = Field(default_factory=list)

    database_url: SecretStr
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_echo: bool = False
    # MySQL closes idle connections after ``wait_timeout`` (8 hours by
    # default); recycling earlier avoids "server has gone away" errors.
    database_pool_recycle_seconds: int = Field(default=1800, ge=60)

    http_timeout_seconds: float = Field(default=10.0, gt=0)
    http_max_connections: int = Field(default=100, ge=1)

    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    # The wallet has no refresh flow, so an access token lives as long
    # as its session. Logging out or changing the password ends the
    # session, which invalidates the token immediately.
    session_lifetime_days: int = Field(default=30, ge=1, le=90)
    registration_token_minutes: int = Field(default=15, ge=1, le=60)

    # Keys the stored HMAC of OTP codes and password reset tokens, so a
    # leaked database alone cannot be used to confirm a code.
    token_hash_secret: SecretStr = Field(min_length=32)

    otp_ttl_minutes: int = Field(default=10, ge=1, le=60)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=0, le=3600)

    login_max_failed_attempts: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)

    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=1440)
    # "{token}" is replaced with the reset token; usually a deep link
    # into the wallet app. A URL template, not a secret.
    password_reset_url: str = "everycredwallet://reset-password?token={token}"  # noqa: S105

    connector_base_url: str
    connector_api_key: SecretStr
    # Shared with the connector; verifies its event webhooks.
    connector_webhook_secret: SecretStr = Field(min_length=32)
    connector_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    webhook_tolerance_seconds: int = Field(default=300, ge=30, le=3600)

    did_prefix: str = Field(
        default="did:evrc:holder", pattern=r"^did:[a-z0-9]+(:[a-z0-9]+)*$"
    )
    max_keys_per_holder: int = Field(default=10, ge=1, le=100)

    # Holder files. "local" writes under STORAGE_LOCAL_DIR and serves
    # them at /media, for development only; "s3" returns presigned URLs.
    storage_backend: StorageBackend = StorageBackend.LOCAL
    storage_local_dir: str = "media"
    storage_public_base_url: str = "http://127.0.0.1:8040/media"
    storage_url_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    aws_region: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str = Field(
        default="holder-service", pattern=r"^[A-Za-z0-9!_.*'()/-]{1,200}$"
    )
    max_profile_image_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    max_presentation_bytes: int = Field(default=1024 * 1024, ge=1024)

    email_backend: EmailBackend = EmailBackend.CONSOLE
    email_from: EmailStr = "no-reply@example.com"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_starttls: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    credential_email_hourly_limit: int = Field(default=10, ge=1, le=100)

    # Live notifications. Socket events are published to the Redis
    # channel the EveryCRED Socket service subscribes to; pushes go to
    # FCM. Either is skipped when not configured.
    socket_redis_url: SecretStr | None = None
    socket_channel: str = "socketio_notifications"
    socket_event: str = "new_request"
    fcm_project_id: str | None = None
    fcm_service_account_json: SecretStr | None = None
    notification_redirect_base_url: str = "everycredwallet://"
    notification_max_attempts: int = Field(default=8, ge=1, le=20)

    # Background worker: notification delivery.
    worker_interval_seconds: float = Field(default=5.0, gt=0, le=300)

    @model_validator(mode="after")
    def check_storage(self) -> "Settings":
        """Require S3 settings for S3, and S3 in production.

        Production containers have a read-only filesystem, and local
        files would not be shared between replicas.
        """
        if (
            self.environment is Environment.PRODUCTION
            and self.storage_backend is not StorageBackend.S3
        ):
            raise ValueError("STORAGE_BACKEND must be 's3' in production")
        if self.storage_backend is StorageBackend.S3 and not (
            self.aws_region and self.s3_bucket
        ):
            raise ValueError(
                "AWS_REGION and S3_BUCKET are required when "
                "STORAGE_BACKEND is 's3'"
            )
        return self

    @model_validator(mode="after")
    def check_email(self) -> "Settings":
        """Require SMTP in production and a host whenever SMTP is used."""
        if (
            self.environment is Environment.PRODUCTION
            and self.email_backend is not EmailBackend.SMTP
        ):
            raise ValueError("EMAIL_BACKEND must be 'smtp' in production")
        if self.email_backend is EmailBackend.SMTP and not self.smtp_host:
            raise ValueError(
                "SMTP_HOST is required when EMAIL_BACKEND is smtp"
            )
        return self

    @model_validator(mode="after")
    def check_urls(self) -> "Settings":
        """Reject malformed URLs and templates at startup."""
        if not self.connector_base_url.startswith(("https://", "http://")):
            raise ValueError("CONNECTOR_BASE_URL must be an http(s) URL")
        if "{token}" not in self.password_reset_url:
            raise ValueError("PASSWORD_RESET_URL must contain {token}")
        if bool(self.fcm_project_id) != bool(self.fcm_service_account_json):
            raise ValueError(
                "FCM_PROJECT_ID and FCM_SERVICE_ACCOUNT_JSON must be set "
                "together"
            )
        return self

    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    The result is cached, so the environment is parsed once. Tests that
    change environment variables should call
    ``get_settings.cache_clear()`` afterwards.
    """
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
