from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.models import utc_now
from app.features.auth.models import EmailOtp, PasswordResetToken
from app.features.holders.models import Holder
from tests.conftest import (
    PASSWORD,
    RecordingMailer,
    RegisteredHolder,
    login,
    register_holder,
    verify_email,
)

OTP_SEND = "/v1/wallet/holder/otp/send"
OTP_VERIFY = "/v1/wallet/holder/otp/verify"


def _register_body(email: str, **overrides: str) -> dict[str, str]:
    return {
        "name": "Test Holder",
        "email": email,
        "password": PASSWORD,
        "confirm_password": PASSWORD,
        **overrides,
    }


async def test_otp_send_returns_dcs_envelope(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    response = await client.post(
        OTP_SEND, json={"email": "new@example.com", "otp_type": "email"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["message"] == "OTP sent successfully"
    assert body["data"]["otp_uuid"]
    assert len(mailer.last_code()) == 6


async def test_otp_send_refuses_registered_email(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        OTP_SEND, json={"email": holder.email, "otp_type": "email"}
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "fail",
        "data": None,
        "message": "Email already exist",
    }


async def test_wrong_otp_reports_remaining_attempts(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    email = "guess@example.com"
    await client.post(OTP_SEND, json={"email": email, "otp_type": "email"})
    wrong = "000000" if mailer.last_code() != "000000" else "111111"
    attempt = {"email": email, "otp_code": wrong, "otp_type": "email"}

    first = await client.post(OTP_VERIFY, json=attempt)
    second = await client.post(OTP_VERIFY, json=attempt)
    third = await client.post(OTP_VERIFY, json=attempt)

    assert first.status_code == 400
    assert first.json()["message"] == "Invalid OTP. 2 attempt(s) remaining"
    assert first.json()["data"] == {"remaining_attempts": 2, "max_attempts": 3}
    assert second.json()["data"]["remaining_attempts"] == 1
    assert third.json()["data"] == {"remaining_attempts": 0, "max_attempts": 3}
    assert third.json()["message"].startswith("Maximum attempts reached")


async def test_verified_otp_cannot_be_verified_again(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    await verify_email(client, mailer, "twice@example.com")

    response = await client.post(
        OTP_VERIFY,
        json={
            "email": "twice@example.com",
            "otp_code": mailer.last_code(),
            "otp_type": "email",
        },
    )

    assert response.status_code == 400
    assert response.json()["message"] == "OTP already verified"


async def test_register_requires_verified_email(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/holder/register", json=_register_body("nootp@example.com")
    )

    assert response.status_code == 400
    assert "verify your email" in response.json()["message"]


async def test_register_rejects_mismatched_passwords(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    await verify_email(client, mailer, "mismatch@example.com")

    response = await client.post(
        "/v1/holder/register",
        json=_register_body(
            "mismatch@example.com", confirm_password="Different9!"
        ),
    )

    assert response.status_code == 400
    assert response.json()["message"] == (
        "Password and confirm password do not match!"
    )


async def test_register_returns_201_with_null_data(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    await verify_email(client, mailer, "fresh@example.com")

    response = await client.post(
        "/v1/holder/register", json=_register_body("fresh@example.com")
    )

    assert response.status_code == 201
    assert response.json() == {
        "status": "success",
        "data": None,
        "message": "Holder created successfully!",
    }


async def test_one_verification_registers_one_account(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        "/v1/holder/register", json=_register_body(holder.email)
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Account already exists!"


async def test_validate_holder(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    by_did = await client.post("/v1/holder/validate", json={"did": holder.did})
    unknown = await client.post(
        "/v1/holder/validate", json={"email": "nobody@example.com"}
    )

    assert by_did.status_code == 200
    assert by_did.json()["message"] == "Holder validated successfully!"
    assert unknown.status_code == 400
    assert unknown.json()["message"] == "DID or holder not found!"


async def test_login_returns_dcs_token_shape(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        "/v1/holder/login", json={"did": holder.did, "password": PASSWORD}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["message"] == "logged in successfully"
    assert body["data"]["user_type"] == "holder"
    assert body["data"]["is_deleted"] is False
    assert body["data"]["token"]


async def test_login_failures_use_dcs_messages(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    unknown = await client.post(
        "/v1/holder/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )
    wrong = await client.post(
        "/v1/holder/login",
        json={"email": holder.email, "password": "WrongPass9!"},
    )

    assert unknown.status_code == 404
    assert wrong.status_code == 400
    for response in (unknown, wrong):
        assert response.json()["message"] == "Email or Password is invalid"


async def test_repeated_failures_lock_the_account(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    for _ in range(3):
        await client.post(
            "/v1/holder/login",
            json={"email": holder.email, "password": "WrongPass9!"},
        )

    response = await client.post(
        "/v1/holder/login", json={"email": holder.email, "password": PASSWORD}
    )

    assert response.status_code == 429


async def test_missing_token_is_reported_like_the_dcs(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/holder")

    assert response.status_code == 401
    assert response.json() == {
        "status": 401,
        "data": None,
        "message": "Not authenticated",
    }


async def test_invalid_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/v1/holder", headers={"Authorization": "Bearer not-a-token"}
    )

    assert response.status_code == 401
    assert response.json()["message"] == "Invalid token"
    assert response.json()["status"] == "fail"


async def test_password_change_rules(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    url = "/v1/holder/password/change"
    mismatch = await client.post(
        url,
        json={
            "current_password": PASSWORD,
            "new_password": "NewPass9!",
            "confirm_password": "Other9!xx",
        },
        headers=holder.headers,
    )
    wrong_current = await client.post(
        url,
        json={
            "current_password": "WrongPass9!",
            "new_password": "NewPass9!",
            "confirm_password": "NewPass9!",
        },
        headers=holder.headers,
    )
    same = await client.post(
        url,
        json={
            "current_password": PASSWORD,
            "new_password": PASSWORD,
            "confirm_password": PASSWORD,
        },
        headers=holder.headers,
    )

    assert mismatch.json()["message"] == (
        "Your new password and confirm password does not match!"
    )
    assert wrong_current.json()["message"] == "Current password is incorrect!"
    assert same.status_code == 400
    assert "different" in same.json()["message"]


async def test_password_change_returns_profile_and_ends_other_sessions(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    other_token = await login(client, holder.email)

    response = await client.post(
        "/v1/holder/password/change",
        json={
            "current_password": PASSWORD,
            "new_password": "NewPass9!",
            "confirm_password": "NewPass9!",
        },
        headers=holder.headers,
    )
    other = await client.get(
        "/v1/holder", headers={"Authorization": f"Bearer {other_token}"}
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert response.json()["message"] == "Password changed successfully"
    assert data["id"] == holder.holder_id
    assert "phone_number" in data
    assert "contact" not in data
    assert other.status_code == 401
    assert await login(client, holder.email, "NewPass9!")


async def test_forget_always_answers_200(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    sent_before = len(mailer.sent)
    known = await client.post(
        "/v1/holder/forget", json={"email": holder.email}
    )
    unknown = await client.post(
        "/v1/holder/forget", json={"email": "nobody@example.com"}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert len(mailer.sent) == sent_before + 1


async def _reset_token(
    client: AsyncClient, mailer: RecordingMailer, email: str
) -> str:
    await client.post("/v1/holder/forget", json={"email": email})
    return mailer.sent[-1].body.split("token=", 1)[1].split()[0]


async def test_reset_submit_and_reuse(
    client: AsyncClient, holder: RegisteredHolder, mailer: RecordingMailer
) -> None:
    token = await _reset_token(client, mailer, holder.email)
    form = {"new_password": "ResetPass9!", "confirm_password": "ResetPass9!"}

    first = await client.post(f"/v1/holder/reset/{token}/submit", data=form)
    again = await client.post(f"/v1/holder/reset/{token}/submit", data=form)
    unknown = await client.post(
        f"/v1/holder/reset/{'x' * 32}/submit", data=form
    )

    assert first.status_code == 200
    assert first.json()["message"] == "Password reset successfully"
    assert again.status_code == 400
    assert again.json()["data"] == {"state": "superseded"}
    assert unknown.json()["data"] == {"state": "invalid"}
    assert await login(client, holder.email, "ResetPass9!")


async def test_expired_reset_link_reports_its_state(
    client: AsyncClient,
    holder: RegisteredHolder,
    mailer: RecordingMailer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = await _reset_token(client, mailer, holder.email)
    async with session_factory() as session:
        await session.execute(
            update(PasswordResetToken).values(
                expires_at=utc_now() - timedelta(minutes=1)
            )
        )
        await session.commit()

    response = await client.post(
        f"/v1/holder/reset/{token}/submit",
        data={
            "new_password": "ResetPass9!",
            "confirm_password": "ResetPass9!",
        },
    )

    assert response.status_code == 400
    assert response.json()["data"] == {"state": "expired"}


async def test_delete_then_recover_account(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    deleted = await client.delete("/v1/holder", headers=holder.headers)
    after_delete = await client.get("/v1/holder", headers=holder.headers)
    login_response = await client.post(
        "/v1/holder/login", json={"email": holder.email, "password": PASSWORD}
    )
    recovery_token = login_response.json()["data"]["token"]
    recovered = await client.post(
        "/v1/holder/recover", json={"recovery_token": recovery_token}
    )
    new_token = recovered.json()["data"]["token"]
    profile = await client.get(
        "/v1/holder", headers={"Authorization": f"Bearer {new_token}"}
    )

    assert deleted.json()["message"] == "Holder deleted successfully!"
    assert after_delete.status_code == 401
    assert login_response.json()["data"]["is_deleted"] is True
    assert "recently deleted" in login_response.json()["message"]
    # The recovery token is not an access token.
    assert (
        await client.get(
            "/v1/holder",
            headers={"Authorization": f"Bearer {recovery_token}"},
        )
    ).status_code == 401
    assert recovered.status_code == 200
    assert recovered.json()["message"] == (
        "Your account has been successfully recovered!"
    )
    assert profile.json()["data"]["id"] == holder.holder_id


async def test_recover_rejects_forged_token(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/holder/recover", json={"recovery_token": "abc.def"}
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid token"


async def _delete_long_ago(
    session_factory: async_sessionmaker[AsyncSession], email: str
) -> None:
    long_ago = utc_now() - timedelta(days=31)
    async with session_factory() as session:
        await session.execute(
            update(Holder)
            .where(Holder.email == email)
            .values(deleted_at=long_ago)
        )
        # The registration OTP is as old as the account, so the resend
        # cooldown does not apply any more.
        await session.execute(
            update(EmailOtp)
            .where(EmailOtp.email == email)
            .values(created_at=long_ago)
        )
        await session.commit()


async def test_deleted_account_past_grace_cannot_sign_in(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _delete_long_ago(session_factory, holder.email)

    response = await client.post(
        "/v1/holder/login", json={"email": holder.email, "password": PASSWORD}
    )

    assert response.status_code == 403
    assert "no longer recoverable" in response.json()["message"]


async def test_email_past_grace_can_register_again(
    client: AsyncClient,
    holder: RegisteredHolder,
    mailer: RecordingMailer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _delete_long_ago(session_factory, holder.email)

    again = await register_holder(client, mailer, holder.email)

    async with session_factory() as session:
        holders = (await session.scalars(select(Holder))).all()
    assert [row.numeric_id for row in holders] == [again.holder_id]
    assert again.holder_id != holder.holder_id


@pytest.mark.parametrize(
    "body",
    [
        {"email": "x@example.com", "otp_type": "email", "extra": 1},
        {"email": "x@example.com", "otp_type": "fax"},
    ],
)
async def test_invalid_otp_requests_use_dcs_validation_shape(
    client: AsyncClient, body: dict[str, object]
) -> None:
    response = await client.post(OTP_SEND, json=body)

    payload = response.json()
    assert response.status_code == 422
    assert payload["status"] == 422
    assert payload["data"] is None
    assert payload["errors"]
    assert payload["message"].startswith(payload["errors"][0]["field"])
