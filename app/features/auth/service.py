"""Holder registration, sign-in, sessions, and password management.

Registration is two steps: the holder proves control of an email with
an emailed OTP, which yields a short-lived registration token; the
registration call then creates the account, the DID, and the first
session. Every later sign-in creates a new session.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import EmailDeliveryError, EmailSender, OutgoingEmail
from app.core.exceptions import ExternalServiceError, TooManyRequestsError
from app.core.models import utc_now
from app.core.security import (
    TokenType,
    burn_password_check_time,
    create_access_token,
    create_registration_token,
    decode_token,
    generate_otp_code,
    generate_url_token,
    hash_password,
    hash_secret_value,
    is_secret_value_valid,
    verify_password,
)
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    InvalidOtpError,
    InvalidResetTokenError,
)
from app.features.auth.models import (
    EmailOtp,
    HolderSession,
    PasswordResetToken,
)
from app.features.auth.repository import AuthRepository
from app.features.auth.schemas import (
    RegisterRequest,
    RegistrationTokenResponse,
    TokenResponse,
)
from app.features.devices.repository import PushTokenRepository
from app.features.dids.service import DidProvisioner
from app.features.holders.models import Holder
from app.features.holders.repository import HolderRepository

logger = logging.getLogger(__name__)


class AuthService:
    """Owns the holder account lifecycle up to an open session.

    Attributes:
        session: Unit of work; the service commits its own changes.
        settings: Token lifetimes, OTP and lockout limits.
        mailer: Sends OTP codes and reset links.
        did_provisioner: Creates the DID of a new holder.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        mailer: EmailSender,
        did_provisioner: DidProvisioner,
    ) -> None:
        self.session = session
        self.settings = settings
        self.mailer = mailer
        self.did_provisioner = did_provisioner
        self.auth = AuthRepository(session)
        self.holders = HolderRepository(session)
        self.push_tokens = PushTokenRepository(session)
        self.audit = AuditRepository(session)

    async def send_registration_otp(self, email: str) -> None:
        """Email a registration code, at most once per cooldown.

        An address that already has an account gets a notice instead of
        a code, and the response is the same either way, so the endpoint
        cannot be used to find out which emails are registered.

        Raises:
            TooManyRequestsError: A code was sent to this email within
                ``OTP_RESEND_COOLDOWN_SECONDS``.
            ExternalServiceError: The email could not be sent.
        """
        email = email.lower()
        now = utc_now()
        latest = await self.auth.get_latest_otp(email)
        cooldown = timedelta(seconds=self.settings.otp_resend_cooldown_seconds)
        if latest is not None and latest.created_at > now - cooldown:
            raise TooManyRequestsError(
                "A code was sent recently. Wait before asking again."
            )

        code = generate_otp_code()
        self.auth.add(
            EmailOtp(
                email=email,
                code_hash=hash_secret_value(code, self.settings),
                expires_at=now
                + timedelta(minutes=self.settings.otp_ttl_minutes),
            )
        )
        await self.session.commit()

        if await self.holders.get_by_email(email) is not None:
            message = OutgoingEmail(
                recipient=email,
                subject="Your EveryCRED wallet account",
                body=(
                    "Someone asked to register an EveryCRED wallet with "
                    "this address, which already has an account. Sign in "
                    "or reset your password instead. If this was not you, "
                    "ignore this email."
                ),
            )
        else:
            message = OutgoingEmail(
                recipient=email,
                subject="Your EveryCRED verification code",
                body=(
                    f"Your verification code is {code}. It expires in "
                    f"{self.settings.otp_ttl_minutes} minutes."
                ),
            )
        await self._send(message)

    async def verify_registration_otp(
        self, email: str, code: str
    ) -> RegistrationTokenResponse:
        """Check a code and return a registration token for the email.

        Raises:
            InvalidOtpError: No usable code, or the code is wrong. Wrong
                guesses count towards ``OTP_MAX_ATTEMPTS``.
        """
        email = email.lower()
        otp = await self.auth.get_latest_otp(email)
        if (
            otp is None
            or otp.consumed_at is not None
            or otp.expires_at <= utc_now()
            or otp.attempts >= self.settings.otp_max_attempts
        ):
            raise InvalidOtpError("The code is invalid or has expired.")
        if not is_secret_value_valid(code, otp.code_hash, self.settings):
            otp.attempts += 1
            await self.session.commit()
            raise InvalidOtpError("The code is invalid or has expired.")

        otp.consumed_at = utc_now()
        await self.session.commit()
        token = create_registration_token(email, self.settings)
        return RegistrationTokenResponse(
            registration_token=token.token, expires_at=token.expires_at
        )

    async def register(self, payload: RegisterRequest) -> TokenResponse:
        """Create the holder, their DID, and a first session.

        Raises:
            AuthenticationError: The registration token is invalid.
            EmailAlreadyRegisteredError: The email has an account.
        """
        claims = decode_token(
            payload.registration_token, TokenType.REGISTRATION, self.settings
        )
        email = claims.subject
        if await self.holders.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError(
                "This email already has an account."
            )

        holder_id = uuid.uuid4()
        did = await self.did_provisioner.provision(holder_id)
        holder = Holder(
            id=holder_id,
            email=email,
            did=did.did,
            full_name=payload.full_name,
            mobile=payload.mobile,
            password_hash=await hash_password(payload.password),
            qr_code_key=did.qr_code_key,
            profile_document_key=did.profile_document_key,
        )
        self.holders.add(holder)
        self.audit.record(holder_id, AuditAction.REGISTERED)
        token = self._open_session(holder)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            # Two registrations for the same email raced past the check.
            await self.session.rollback()
            raise EmailAlreadyRegisteredError(
                "This email already has an account."
            ) from exc
        logger.info("Holder %s registered", holder_id)
        return token

    async def login(self, identifier: str, password: str) -> TokenResponse:
        """Verify credentials and open a new session.

        Raises:
            InvalidCredentialsError: For any failure, including a locked
                or inactive account.
        """
        holder = await self.holders.get_by_email_or_did(identifier)
        if holder is None:
            await burn_password_check_time(password)
            raise InvalidCredentialsError("Invalid email, DID or password.")

        now = utc_now()
        is_locked = (
            holder.locked_until is not None and holder.locked_until > now
        )
        # The password is checked even for locked accounts so the
        # response time does not reveal the lock.
        check = await verify_password(password, holder.password_hash)
        if is_locked or not holder.is_active or not check.is_valid:
            if not is_locked and holder.is_active:
                self._count_failed_login(holder)
            self.audit.record(holder.id, AuditAction.LOGIN_FAILED)
            await self.session.commit()
            raise InvalidCredentialsError("Invalid email, DID or password.")

        holder.failed_login_count = 0
        holder.locked_until = None
        if check.updated_hash:
            holder.password_hash = check.updated_hash
        token = self._open_session(holder)
        self.audit.record(holder.id, AuditAction.LOGIN_SUCCEEDED)
        await self.session.commit()
        return token

    async def logout(self, holder: Holder, session: HolderSession) -> None:
        """End the current session and stop its pushes."""
        session.ended_at = utc_now()
        await self.push_tokens.deactivate_for_sessions([session.id])
        self.audit.record(holder.id, AuditAction.LOGGED_OUT)
        await self.session.commit()

    async def change_password(
        self,
        holder: Holder,
        session: HolderSession,
        current_password: str,
        new_password: str,
    ) -> None:
        """Replace the password and sign out every other session.

        Raises:
            InvalidCurrentPasswordError: ``current_password`` is wrong.
        """
        check = await verify_password(current_password, holder.password_hash)
        if not check.is_valid:
            raise InvalidCurrentPasswordError(
                "The current password is incorrect."
            )
        now = utc_now()
        holder.password_hash = await hash_password(new_password)
        ended = await self.auth.end_sessions(
            holder.id, now, except_session_id=session.id
        )
        await self.push_tokens.deactivate_for_sessions(ended)
        await self.auth.consume_open_reset_tokens(holder.id, now)
        self.audit.record(holder.id, AuditAction.PASSWORD_CHANGED)
        await self.session.commit()

    async def request_password_reset(self, email: str) -> None:
        """Email a single-use reset link if the email has an account.

        Nothing different happens for unknown emails, and delivery
        failures are only logged, so the endpoint cannot be used to find
        out which emails are registered.
        """
        holder = await self.holders.get_by_email(email)
        if holder is None or not holder.is_active:
            return
        now = utc_now()
        await self.auth.consume_open_reset_tokens(holder.id, now)
        token = generate_url_token()
        self.auth.add(
            PasswordResetToken(
                holder_id=holder.id,
                token_hash=hash_secret_value(token, self.settings),
                expires_at=now
                + timedelta(minutes=self.settings.password_reset_ttl_minutes),
            )
        )
        await self.session.commit()
        link = self.settings.password_reset_url.replace("{token}", token)
        try:
            await self.mailer.send(
                OutgoingEmail(
                    recipient=holder.email,
                    subject="Reset your EveryCRED wallet password",
                    body=(
                        f"Open this link to choose a new password: {link}\n"
                        "It expires in "
                        f"{self.settings.password_reset_ttl_minutes} "
                        "minutes and works once. If you did not ask for "
                        "this, ignore this email."
                    ),
                )
            )
        except EmailDeliveryError:
            logger.error("Reset email for holder %s was not sent", holder.id)

    async def reset_password(self, token: str, new_password: str) -> None:
        """Set a new password with a reset token and end every session.

        Raises:
            InvalidResetTokenError: The token is unknown, used, or
                expired.
        """
        now = utc_now()
        reset = await self.auth.get_reset_token(
            hash_secret_value(token, self.settings)
        )
        if reset is None or reset.consumed_at is not None:
            raise InvalidResetTokenError("The reset link is invalid.")
        if reset.expires_at <= now:
            raise InvalidResetTokenError("The reset link has expired.")
        holder = await self.holders.get_by_id(reset.holder_id)
        if holder is None or not holder.is_active:
            raise InvalidResetTokenError("The reset link is invalid.")

        holder.password_hash = await hash_password(new_password)
        holder.failed_login_count = 0
        holder.locked_until = None
        reset.consumed_at = now
        ended = await self.auth.end_sessions(holder.id, now)
        await self.push_tokens.deactivate_for_sessions(ended)
        self.audit.record(holder.id, AuditAction.PASSWORD_RESET)
        await self.session.commit()

    def _open_session(self, holder: Holder) -> TokenResponse:
        expires_at = utc_now() + timedelta(
            days=self.settings.session_lifetime_days
        )
        holder_session = HolderSession(
            id=uuid.uuid4(), holder_id=holder.id, expires_at=expires_at
        )
        self.auth.add(holder_session)
        token = create_access_token(
            holder.id, holder_session.id, expires_at, self.settings
        )
        return TokenResponse(
            access_token=token.token,
            expires_at=token.expires_at,
            holder_id=holder.id,
            did=holder.did,
        )

    def _count_failed_login(self, holder: Holder) -> None:
        holder.failed_login_count += 1
        if (
            holder.failed_login_count
            >= self.settings.login_max_failed_attempts
        ):
            holder.locked_until = utc_now() + timedelta(
                minutes=self.settings.login_lockout_minutes
            )
            holder.failed_login_count = 0
            logger.warning("Holder %s locked after failed logins", holder.id)

    async def _send(self, message: OutgoingEmail) -> None:
        try:
            await self.mailer.send(message)
        except EmailDeliveryError as exc:
            raise ExternalServiceError(
                "The email could not be sent. Try again later."
            ) from exc
