"""Holder registration, sign-in, sessions, recovery, and passwords.

The flows follow the DCS endpoints the wallet app calls, with the same
messages, so the app behaves the same against this service:

* Registration: ``otp/send`` emails a code, ``otp/verify`` checks it,
  and ``register`` creates the account. Unlike the DCS, ``register``
  requires a verification of that email within
  ``REGISTRATION_TOKEN_MINUTES``; the app always verifies first.
* ``otp/verify`` also returns a single-use login token. Once
  ``register`` has used that verification, ``login/otp`` exchanges the
  token for a session, so the app signs in without asking for the
  password again.
* Registration also claims the issuer invites that were waiting for the
  email and queues a report of the new account to every linked DCS
  (see ``app.features.onboarding``).
* Sign-in opens a session. A deleted account can be recovered within
  ``ACCOUNT_DELETION_GRACE_DAYS`` through a short-lived recovery token.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import EmailDeliveryError, EmailSender, OutgoingEmail
from app.core.exceptions import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    TooManyRequestsError,
)
from app.core.models import utc_now
from app.core.security import (
    RecoveryTokenError,
    TokenType,
    burn_password_check_time,
    create_access_token,
    create_email_verification_token,
    create_recovery_token,
    decode_token,
    generate_otp_code,
    generate_url_token,
    hash_password,
    hash_secret_value,
    is_secret_value_valid,
    read_recovery_token,
    verify_password,
)
from app.features.audit.models import AuditAction
from app.features.audit.repository import AuditRepository
from app.features.auth.exceptions import (
    GRACE_EXPIRED_MESSAGE,
    INVALID_LOGIN_MESSAGE,
    AccountLockedError,
    AccountNotRecoverableError,
    InvalidEmailVerificationError,
    InvalidLoginError,
    InvalidLoginTokenError,
    InvalidOtpError,
    InvalidRecoveryError,
    InvalidResetLinkError,
    PasswordChangeError,
    RegistrationError,
    SocialLoginError,
    UnknownHolderLoginError,
)
from app.features.auth.google import (
    GoogleIdTokenVerifier,
    InvalidGoogleTokenError,
)
from app.features.auth.models import (
    EmailOtp,
    HolderSession,
    PasswordResetToken,
)
from app.features.auth.repository import AuthRepository
from app.features.auth.schemas import (
    LoginRequest,
    OtpLoginRequest,
    OtpType,
    RegisterRequest,
    SendOtpRequest,
    SsoType,
    VerifyOtpRequest,
)
from app.features.devices.repository import PushTokenRepository
from app.features.dids.service import DidProvisioner
from app.features.holders.models import Holder
from app.features.holders.repository import HolderRepository
from app.features.onboarding.service import OnboardingService

logger = logging.getLogger(__name__)

USER_TYPE_HOLDER = "holder"
_RESET_LINK_EXPIRED = (
    "This password reset link has expired. Please request a new one."
)
_RESET_LINK_SUPERSEDED = (
    "This password reset link is no longer valid. It has already been used "
    "or a newer link was requested. Please use the most recent link sent "
    "to your email."
)
_RESET_LINK_INVALID = "This password reset link is invalid."
INVALID_TOKEN_MESSAGE = "Invalid token"  # noqa: S105 - a message
_SSO_UNREGISTERED = "Please register!"
_SSO_DELETED = (
    "This account was recently deleted. Sign in with your password to "
    "recover it."
)
_AUTO_SIGN_IN_UNAVAILABLE = (
    "Automatic sign-in is no longer available. Please log in with your "
    "password."
)
_AUTO_SIGN_IN_UNREGISTERED = "Please complete registration before signing in."


@dataclass(frozen=True, slots=True)
class AuthResult:
    """What an auth endpoint returns in the envelope."""

    data: dict[str, Any] | None
    message: str


class AuthService:
    """Owns the holder account lifecycle up to an open session.

    Attributes:
        session: Unit of work; the service commits its own changes.
        settings: Token lifetimes, OTP, lockout and grace limits.
        mailer: Sends OTP codes and reset links.
        did_provisioner: Creates the DID of a new holder.
        google_verifier: Checks Google ID tokens for social sign-in.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        mailer: EmailSender,
        did_provisioner: DidProvisioner,
        google_verifier: GoogleIdTokenVerifier,
    ) -> None:
        self.session = session
        self.settings = settings
        self.mailer = mailer
        self.did_provisioner = did_provisioner
        self.google_verifier = google_verifier
        self.auth = AuthRepository(session)
        self.holders = HolderRepository(session)
        self.push_tokens = PushTokenRepository(session)
        self.audit = AuditRepository(session)
        self.onboarding = OnboardingService(session, settings)

    async def validate_holder(
        self, email: str | None, did: str | None
    ) -> None:
        """Check that an active holder has this email or DID.

        Raises:
            RegistrationError: Neither is given, or no holder matches.
        """
        if not email and not did:
            raise RegistrationError("Email or DID required")
        holder = (
            await self.holders.get_by_email(email)
            if email
            else await self.holders.get_by_did(str(did))
        )
        if holder is None or holder.is_deleted:
            raise RegistrationError("DID or holder not found!")

    async def send_otp(self, payload: SendOtpRequest) -> AuthResult:
        """Email a registration code, at most once per cooldown.

        Raises:
            RegistrationError: Mobile OTP was asked for, no email was
                given, or the email already has an account.
            TooManyRequestsError: A code was sent to this email within
                ``OTP_RESEND_COOLDOWN_SECONDS``.
            ExternalServiceError: The email could not be sent.
        """
        if payload.otp_type is OtpType.MOBILE:
            raise RegistrationError(
                "Mobile OTP is not supported. Please use your email."
            )
        if not payload.email:
            raise RegistrationError("Email is required")
        email = payload.email.lower()
        existing = await self.holders.get_by_email(email)
        if existing is not None and not self._is_beyond_grace(existing):
            raise RegistrationError("Email already exist")

        now = utc_now()
        latest = await self.auth.get_latest_otp(email)
        cooldown = timedelta(seconds=self.settings.otp_resend_cooldown_seconds)
        if latest is not None and latest.created_at > now - cooldown:
            raise TooManyRequestsError(
                "An OTP was sent recently. Please wait before requesting "
                "a new one."
            )
        code = generate_otp_code()
        otp = EmailOtp(
            id=uuid.uuid4(),
            email=email,
            code_hash=hash_secret_value(code, self.settings),
            expires_at=now + timedelta(minutes=self.settings.otp_ttl_minutes),
        )
        self.auth.add(otp)
        await self.session.commit()
        await self._send(
            OutgoingEmail(
                recipient=email,
                subject="Your EveryCRED verification code",
                body=(
                    f"Your verification code is {code}. It expires in "
                    f"{self.settings.otp_ttl_minutes} minutes."
                ),
            )
        )
        return AuthResult({"otp_uuid": str(otp.id)}, "OTP sent successfully")

    async def verify_otp(self, payload: VerifyOtpRequest) -> AuthResult:
        """Check an emailed code; wrong guesses count against the limit.

        Raises:
            InvalidOtpError: No usable code, or the code is wrong. Wrong
                codes carry ``remaining_attempts`` and ``max_attempts``
                in ``data``, which the app reads.
        """
        if payload.otp_type is OtpType.MOBILE or not payload.email:
            raise InvalidOtpError("Invalid OTP or OTP not found")
        otp = await self.auth.get_latest_otp(payload.email.lower())
        max_attempts = self.settings.otp_max_attempts
        if otp is None:
            raise InvalidOtpError("Invalid OTP or OTP not found")
        if otp.consumed_at is not None:
            raise InvalidOtpError("OTP already verified")
        if otp.expires_at <= utc_now():
            raise InvalidOtpError("OTP has expired")
        if otp.attempts >= max_attempts:
            raise self._attempts_exhausted(max_attempts)
        if not is_secret_value_valid(
            payload.otp_code, otp.code_hash, self.settings
        ):
            otp.attempts += 1
            await self.session.commit()
            remaining = max_attempts - otp.attempts
            if remaining <= 0:
                raise self._attempts_exhausted(max_attempts)
            raise InvalidOtpError(
                f"Invalid OTP. {remaining} attempt(s) remaining",
                data={
                    "remaining_attempts": remaining,
                    "max_attempts": max_attempts,
                },
            )
        login_token = generate_url_token()
        otp.consumed_at = utc_now()
        otp.login_token_hash = hash_secret_value(login_token, self.settings)
        await self.session.commit()
        return AuthResult(
            {
                "verified": True,
                "otp_uuid": str(otp.id),
                "login_token": login_token,
            },
            "OTP verified successfully",
        )

    async def register(self, payload: RegisterRequest) -> None:
        """Create the holder and their DID after OTP verification.

        A holder whose account was deleted longer ago than the grace
        period is replaced, so the email can be registered again.

        Raises:
            RegistrationError: Passwords differ, the email has an
                account, or the email was not verified recently.
        """
        if payload.password != payload.confirm_password:
            raise RegistrationError(
                "Password and confirm password do not match!"
            )
        email = payload.email.lower()
        existing = await self.holders.get_by_email(email)
        if existing is not None and not self._is_beyond_grace(existing):
            raise RegistrationError("Account already exists!")
        otp = await self.auth.get_latest_otp(email)
        window = timedelta(minutes=self.settings.registration_token_minutes)
        if (
            otp is None
            or otp.consumed_at is None
            or otp.used_at is not None
            or otp.consumed_at <= utc_now() - window
        ):
            raise RegistrationError(
                "Please verify your email with the OTP before registering."
            )

        if existing is not None:
            await self.holders.delete(existing)
            await self.session.flush()
            logger.info(
                "Replacing holder %s past its grace period", existing.id
            )
        otp.used_at = utc_now()
        holder = await self._create_holder(email, payload)
        self.audit.record(holder.id, AuditAction.REGISTERED)
        invite_count = await self.onboarding.claim_invites(holder)
        await self.session.commit()
        logger.info(
            "Holder %s registered with %d pending invite(s)",
            holder.id,
            invite_count,
        )

    async def login(self, payload: LoginRequest) -> AuthResult:
        """Verify credentials and open a session, or offer recovery.

        Raises:
            InvalidLoginError: No identifier, wrong password, or an
                inactive account.
            UnknownHolderLoginError: No holder has the email or DID.
            AccountLockedError: Too many recent failed attempts.
            AccountNotRecoverableError: The account was deleted and its
                grace period is over.
        """
        if not payload.email and not payload.did:
            raise InvalidLoginError("Email or DID required")
        holder = (
            await self.holders.get_by_email(payload.email)
            if payload.email
            else await self.holders.get_by_did(str(payload.did))
        )
        if holder is None:
            await burn_password_check_time(payload.password)
            raise UnknownHolderLoginError(INVALID_LOGIN_MESSAGE)

        now = utc_now()
        is_locked = (
            holder.locked_until is not None and holder.locked_until > now
        )
        # The password is checked even for locked accounts so the
        # response time does not reveal the lock.
        check = await verify_password(payload.password, holder.password_hash)
        if is_locked:
            raise AccountLockedError(
                "Too many failed sign-in attempts. Please try again in "
                f"{self.settings.login_lockout_minutes} minutes."
            )
        if not holder.is_active or not check.is_valid:
            if holder.is_active:
                self._count_failed_login(holder)
            self.audit.record(holder.id, AuditAction.LOGIN_FAILED)
            await self.session.commit()
            raise InvalidLoginError(INVALID_LOGIN_MESSAGE)

        holder.failed_login_count = 0
        holder.locked_until = None
        if check.updated_hash:
            holder.password_hash = check.updated_hash
        if holder.is_deleted:
            await self.session.commit()
            if self._is_beyond_grace(holder):
                raise AccountNotRecoverableError(GRACE_EXPIRED_MESSAGE)
            return AuthResult(
                {
                    "is_deleted": True,
                    "token": create_recovery_token(holder.id, self.settings),
                },
                "This account was recently deleted. Would you like to "
                "recover it?",
            )
        token = self._open_session(holder)
        self.audit.record(holder.id, AuditAction.LOGIN_SUCCEEDED)
        await self.session.commit()
        return AuthResult(
            {
                "user_type": USER_TYPE_HOLDER,
                "token": token,
                "is_deleted": False,
            },
            "logged in successfully",
        )

    async def login_with_otp_token(
        self, payload: OtpLoginRequest
    ) -> AuthResult:
        """Open a session for a holder who just registered.

        The token comes from ``verify_otp`` and works once, only after
        ``register`` has used that verification, and only within
        ``REGISTRATION_TOKEN_MINUTES`` of it.

        Raises:
            InvalidLoginTokenError: The token is unknown, used, or
                expired, the email is not registered yet, or the account
                cannot sign in.
        """
        otp = await self.auth.get_otp_by_login_token(
            hash_secret_value(payload.login_token, self.settings)
        )
        window = timedelta(minutes=self.settings.registration_token_minutes)
        now = utc_now()
        if (
            otp is None
            or otp.consumed_at is None
            or otp.signed_in_at is not None
            or otp.consumed_at <= now - window
        ):
            raise InvalidLoginTokenError(_AUTO_SIGN_IN_UNAVAILABLE)
        if otp.used_at is None:
            raise InvalidLoginTokenError(_AUTO_SIGN_IN_UNREGISTERED)
        holder = await self.holders.get_by_email(otp.email)
        if holder is None or not holder.is_active or holder.is_deleted:
            raise InvalidLoginTokenError(_AUTO_SIGN_IN_UNAVAILABLE)
        if not await self.auth.claim_login_token(otp.id, now):
            raise InvalidLoginTokenError(_AUTO_SIGN_IN_UNAVAILABLE)

        token = self._open_session(holder)
        self.audit.record(holder.id, AuditAction.LOGIN_SUCCEEDED)
        await self.session.commit()
        logger.info("Holder %s signed in with an OTP login token", holder.id)
        return AuthResult(
            {
                "user_type": USER_TYPE_HOLDER,
                "token": token,
                "is_deleted": False,
            },
            "logged in successfully",
        )

    async def recover(self, recovery_token: str) -> AuthResult:
        """Restore a recently deleted account and open a session.

        Raises:
            InvalidRecoveryError: The token is expired or invalid, the
                holder no longer exists, or the grace period is over.
        """
        try:
            holder_id = read_recovery_token(recovery_token, self.settings)
        except RecoveryTokenError as exc:
            if exc.is_expired:
                raise InvalidRecoveryError(
                    "This recovery request has expired. Please log in "
                    "again to retry."
                ) from exc
            raise InvalidRecoveryError("Invalid token") from exc
        holder = await self.holders.get_by_id(holder_id)
        if holder is None or not holder.is_active:
            raise InvalidRecoveryError("Holder not found!")
        if self._is_beyond_grace(holder):
            raise InvalidRecoveryError(GRACE_EXPIRED_MESSAGE)
        holder.deleted_at = None
        token = self._open_session(holder)
        self.audit.record(holder.id, AuditAction.ACCOUNT_RECOVERED)
        await self.session.commit()
        logger.info("Holder %s recovered their account", holder.id)
        return AuthResult(
            {"user_type": USER_TYPE_HOLDER, "token": token},
            "Your account has been successfully recovered!",
        )

    async def delete_account(self, holder: Holder) -> None:
        """Soft-delete the account and sign out every device.

        The row is kept for ``ACCOUNT_DELETION_GRACE_DAYS`` so the
        holder can recover it by signing in.
        """
        now = utc_now()
        holder.deleted_at = now
        ended = await self.auth.end_sessions(holder.id, now)
        await self.push_tokens.deactivate_for_sessions(ended)
        self.audit.record(holder.id, AuditAction.ACCOUNT_DELETED)
        await self.session.commit()
        logger.info("Holder %s deleted their account", holder.id)

    async def logout(
        self, holder: Holder, holder_session: HolderSession
    ) -> None:
        """End the session the request was made with.

        Its token stops working at once, and push tokens registered from
        this device stop receiving notifications. Other devices stay
        signed in.
        """
        holder_session.ended_at = utc_now()
        await self.push_tokens.deactivate_for_sessions([holder_session.id])
        self.audit.record(holder.id, AuditAction.LOGGED_OUT)
        await self.session.commit()
        logger.info("Holder %s logged out", holder.id)

    async def sso_login(
        self, sso_type: SsoType, provider_token: str
    ) -> AuthResult:
        """Open a session for the holder behind a Google ID token.

        Only Google is accepted. The DCS "office365" flow took the email
        from the request body without checking it, which would let
        anyone sign in as anyone; "linkedin" needs a web redirect the
        wallet app does not have.

        Raises:
            SocialLoginError: Unsupported provider, Google sign-in not
                configured, an invalid token, or a deleted account.
            NotFoundError: No account has the token's email.
            ExternalServiceError: Google's certificates were unavailable.
        """
        if (
            sso_type is not SsoType.GMAIL
            or not self.google_verifier.is_configured
        ):
            raise SocialLoginError(INVALID_TOKEN_MESSAGE)
        try:
            identity = await self.google_verifier.verify(provider_token)
        except InvalidGoogleTokenError as exc:
            raise SocialLoginError(INVALID_TOKEN_MESSAGE) from exc
        holder = await self.holders.get_by_email(identity.email)
        if holder is None or not holder.is_active:
            raise NotFoundError(_SSO_UNREGISTERED)
        if holder.is_deleted:
            raise SocialLoginError(_SSO_DELETED)
        token = self._open_session(holder)
        self.audit.record(holder.id, AuditAction.LOGIN_SUCCEEDED)
        await self.session.commit()
        return AuthResult(
            {"token": token, "role_type": USER_TYPE_HOLDER},
            "logged in successfully",
        )

    async def send_email_confirmation(self, email: str) -> None:
        """Email a verification link if the email has an account.

        Unknown emails get the same answer and nothing is sent, so the
        endpoint cannot be used to find out which emails are registered.
        Unlike the DCS, the link is never returned in the response: that
        would let anyone "verify" an address they cannot read.
        """
        holder = await self.holders.get_by_email(email)
        if holder is None or not holder.is_active or holder.is_deleted:
            return
        ttl_minutes = self.settings.email_verification_ttl_minutes
        token = create_email_verification_token(
            holder.id,
            utc_now() + timedelta(minutes=ttl_minutes),
            self.settings,
        ).token
        link = self.settings.email_verification_url.replace("{token}", token)
        try:
            await self.mailer.send(
                OutgoingEmail(
                    recipient=holder.email,
                    subject="Verify your EveryCRED wallet email",
                    body=(
                        f"Open this link to verify your email: {link}\n"
                        f"It expires in {ttl_minutes} minutes. If you did "
                        "not ask for this, ignore this email."
                    ),
                )
            )
        except EmailDeliveryError:
            logger.error(
                "Verification email for holder %s was not sent", holder.id
            )

    async def verify_email(self, token: str) -> None:
        """Accept a verification link sent by ``send_email_confirmation``.

        Holders already proved their email with an OTP to register, so
        nothing is stored; the call only confirms the link is genuine.

        Raises:
            InvalidEmailVerificationError: The token is invalid or
                expired, or its holder no longer has an active account.
        """
        try:
            claims = decode_token(
                token, TokenType.EMAIL_VERIFICATION, self.settings
            )
        except AuthenticationError as exc:
            raise InvalidEmailVerificationError(INVALID_TOKEN_MESSAGE) from exc
        holder = await self.holders.get_by_id(uuid.UUID(claims.subject))
        if holder is None or not holder.is_active or holder.is_deleted:
            raise InvalidEmailVerificationError(INVALID_TOKEN_MESSAGE)

    async def change_password(
        self,
        holder: Holder,
        session: HolderSession,
        current_password: str,
        new_password: str,
        confirm_password: str,
    ) -> None:
        """Replace the password and sign out every other session.

        Raises:
            PasswordChangeError: Confirmation differs, the current
                password is wrong, or the new one equals it.
        """
        if new_password != confirm_password:
            raise PasswordChangeError(
                "Your new password and confirm password does not match!"
            )
        check = await verify_password(current_password, holder.password_hash)
        if not check.is_valid:
            raise PasswordChangeError("Current password is incorrect!")
        if new_password == current_password:
            raise PasswordChangeError(
                "The new password must be different from the current password."
            )
        now = utc_now()
        holder.password_hash = await hash_password(new_password)
        holder.updated_at = now
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
        if holder is None or not holder.is_active or holder.is_deleted:
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

    async def reset_password(
        self, token: str, new_password: str, confirm_password: str
    ) -> None:
        """Set a new password from a reset link and end every session.

        Raises:
            InvalidResetLinkError: The link is unknown, used, superseded,
                or expired; ``data.state`` says which.
            PasswordChangeError: The passwords differ or the new one is
                the current password.
        """
        now = utc_now()
        reset = await self.auth.get_reset_token(
            hash_secret_value(token, self.settings)
        )
        holder = (
            await self.holders.get_by_id(reset.holder_id) if reset else None
        )
        if (
            reset is None
            or holder is None
            or not holder.is_active
            or holder.is_deleted
        ):
            raise InvalidResetLinkError(
                _RESET_LINK_INVALID, data={"state": "invalid"}
            )
        if reset.consumed_at is not None:
            raise InvalidResetLinkError(
                _RESET_LINK_SUPERSEDED, data={"state": "superseded"}
            )
        if reset.expires_at <= now:
            raise InvalidResetLinkError(
                _RESET_LINK_EXPIRED, data={"state": "expired"}
            )
        if new_password != confirm_password:
            raise PasswordChangeError("Password does not match")
        if (
            await verify_password(new_password, holder.password_hash)
        ).is_valid:
            raise PasswordChangeError(
                "The new password you entered is the same as the old password."
            )

        holder.password_hash = await hash_password(new_password)
        holder.failed_login_count = 0
        holder.locked_until = None
        reset.consumed_at = now
        ended = await self.auth.end_sessions(holder.id, now)
        await self.push_tokens.deactivate_for_sessions(ended)
        self.audit.record(holder.id, AuditAction.PASSWORD_RESET)
        await self.session.commit()

    async def _create_holder(
        self, email: str, payload: RegisterRequest
    ) -> Holder:
        holder_id = uuid.uuid4()
        did = await self.did_provisioner.provision(holder_id)
        holder = Holder(
            id=holder_id,
            numeric_id=await self.holders.pick_unused_numeric_id(),
            email=email,
            did=did.did,
            full_name=payload.name,
            mobile=payload.contact,
            password_hash=await hash_password(payload.password),
            qr_code_key=did.qr_code_key,
            profile_document_key=did.profile_document_key,
        )
        self.holders.add(holder)
        try:
            # Written before the audit row, which references it; the
            # models declare no relationships to order the inserts.
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            if await self.holders.get_by_email(email) is None:
                raise
            # Two registrations for the same email raced.
            raise RegistrationError("Account already exists!") from exc
        return holder

    def _open_session(self, holder: Holder) -> str:
        expires_at = utc_now() + timedelta(
            days=self.settings.session_lifetime_days
        )
        holder_session = HolderSession(
            id=uuid.uuid4(), holder_id=holder.id, expires_at=expires_at
        )
        self.auth.add(holder_session)
        return create_access_token(
            holder.id, holder_session.id, expires_at, self.settings
        ).token

    def _is_beyond_grace(self, holder: Holder) -> bool:
        if holder.deleted_at is None:
            return False
        grace = timedelta(days=self.settings.account_deletion_grace_days)
        return holder.deleted_at <= utc_now() - grace

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

    @staticmethod
    def _attempts_exhausted(max_attempts: int) -> InvalidOtpError:
        return InvalidOtpError(
            "Maximum attempts reached. Please try again with new OTP.",
            data={"remaining_attempts": 0, "max_attempts": max_attempts},
        )

    async def _send(self, message: OutgoingEmail) -> None:
        try:
            await self.mailer.send(message)
        except EmailDeliveryError as exc:
            raise ExternalServiceError(
                "We could not send the OTP email. Please try again."
            ) from exc
