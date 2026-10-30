from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.models import utc_now
from app.features.auth.models import EmailOtp
from tests.conftest import PASSWORD, RecordingMailer

OTP_SEND = "/v1/wallet/holder/otp/send"
OTP_VERIFY = "/v1/wallet/holder/otp/verify"
REGISTER = "/v1/holder/register"
OTP_LOGIN = "/v1/holder/login/otp"
INVALID_MESSAGE = (
    "Automatic sign-in is no longer available. Please log in with your "
    "password."
)


async def _verify(
    client: AsyncClient, mailer: RecordingMailer, email: str
) -> str:
    await client.post(OTP_SEND, json={"email": email, "otp_type": "email"})
    response = await client.post(
        OTP_VERIFY,
        json={
            "email": email,
            "otp_code": mailer.last_code(),
            "otp_type": "email",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["login_token"]


async def _register(client: AsyncClient, email: str) -> None:
    response = await client.post(
        REGISTER,
        json={
            "name": "Test Holder",
            "email": email,
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text


async def test_verify_keeps_dcs_fields_and_adds_login_token(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    await client.post(
        OTP_SEND, json={"email": "shape@example.com", "otp_type": "email"}
    )

    response = await client.post(
        OTP_VERIFY,
        json={
            "email": "shape@example.com",
            "otp_code": mailer.last_code(),
            "otp_type": "email",
        },
    )

    body = response.json()
    assert body["message"] == "OTP verified successfully"
    assert body["data"]["verified"] is True
    assert body["data"]["otp_uuid"]
    assert len(body["data"]["login_token"]) >= 43


async def test_login_token_signs_in_after_registration(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    login_token = await _verify(client, mailer, "direct@example.com")
    await _register(client, "direct@example.com")

    response = await client.post(OTP_LOGIN, json={"login_token": login_token})

    body = response.json()
    assert response.status_code == 200
    assert body["message"] == "logged in successfully"
    assert body["data"]["user_type"] == "holder"
    assert body["data"]["is_deleted"] is False
    profile = await client.get(
        "/v1/holder",
        headers={"Authorization": f"Bearer {body['data']['token']}"},
    )
    assert profile.json()["data"]["email"] == "direct@example.com"


async def test_login_token_works_once(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    login_token = await _verify(client, mailer, "once@example.com")
    await _register(client, "once@example.com")
    await client.post(OTP_LOGIN, json={"login_token": login_token})

    response = await client.post(OTP_LOGIN, json={"login_token": login_token})

    assert response.status_code == 400
    assert response.json()["message"] == INVALID_MESSAGE


async def test_login_token_needs_registration_first(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    login_token = await _verify(client, mailer, "early@example.com")

    early = await client.post(OTP_LOGIN, json={"login_token": login_token})
    await _register(client, "early@example.com")
    after = await client.post(OTP_LOGIN, json={"login_token": login_token})

    assert early.status_code == 400
    assert early.json()["message"] == (
        "Please complete registration before signing in."
    )
    assert after.status_code == 200


async def test_login_token_expires_with_the_registration_window(
    client: AsyncClient,
    mailer: RecordingMailer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    login_token = await _verify(client, mailer, "late@example.com")
    await _register(client, "late@example.com")
    async with session_factory() as session:
        await session.execute(
            update(EmailOtp)
            .where(EmailOtp.email == "late@example.com")
            .values(consumed_at=utc_now() - timedelta(minutes=16))
        )
        await session.commit()

    response = await client.post(OTP_LOGIN, json={"login_token": login_token})

    assert response.status_code == 400
    assert response.json()["message"] == INVALID_MESSAGE


async def test_unknown_login_token_is_rejected_without_401(
    client: AsyncClient,
) -> None:
    response = await client.post(
        OTP_LOGIN, json={"login_token": "not-a-real-token"}
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "fail",
        "data": None,
        "message": INVALID_MESSAGE,
    }
