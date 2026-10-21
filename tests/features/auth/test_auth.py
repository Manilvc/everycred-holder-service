import pytest
from httpx import AsyncClient, Response

from app.core.config import get_settings
from app.core.security import create_registration_token
from tests.conftest import (
    PASSWORD,
    RecordingMailer,
    RegisteredHolder,
    register_holder,
)

NEW_PASSWORD = "an entirely new passphrase"


async def login(
    client: AsyncClient, identifier: str, password: str = PASSWORD
) -> Response:
    return await client.post(
        "/v1/auth/login",
        json={"identifier": identifier, "password": password},
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def reset_token_from(mailer: RecordingMailer) -> str:
    return mailer.sent[-1].body.split("token=")[1].split()[0]


async def test_otp_resend_within_cooldown_is_refused(
    client: AsyncClient,
) -> None:
    email = {"email": "cooldown@example.com"}
    first = await client.post("/v1/auth/otp/send", json=email)
    second = await client.post("/v1/auth/otp/send", json=email)

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "too_many_requests"


async def test_wrong_otp_counts_attempts_until_code_is_unusable(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    email = "attempts@example.com"
    await client.post("/v1/auth/otp/send", json={"email": email})
    code = mailer.last_code()
    wrong_code = "000000" if code != "000000" else "111111"

    for _ in range(get_settings().otp_max_attempts):
        response = await client.post(
            "/v1/auth/otp/verify", json={"email": email, "code": wrong_code}
        )
        assert response.json()["error"]["code"] == "invalid_otp"
    response = await client.post(
        "/v1/auth/otp/verify", json={"email": email, "code": code}
    )

    assert response.status_code == 400


async def test_otp_code_works_only_once(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    email = "once@example.com"
    await client.post("/v1/auth/otp/send", json={"email": email})
    payload = {"email": email, "code": mailer.last_code()}

    first = await client.post("/v1/auth/otp/verify", json=payload)
    second = await client.post("/v1/auth/otp/verify", json=payload)

    assert first.status_code == 200
    assert second.status_code == 400


async def test_register_creates_holder_with_did(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.get("/v1/holders/me", headers=holder.headers)

    assert response.status_code == 200
    assert response.json()["did"].startswith("did:evrc:holder:")
    assert response.json()["email"] == holder.email


async def test_registered_email_gets_notice_instead_of_code(
    client: AsyncClient,
    mailer: RecordingMailer,
    holder: RegisteredHolder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "otp_resend_cooldown_seconds", 0)

    response = await client.post(
        "/v1/auth/otp/send", json={"email": holder.email}
    )

    assert response.status_code == 202
    assert "already has an account" in mailer.sent[-1].body


async def test_register_twice_with_same_email_conflicts(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    # A registered email never receives a code, so the token is minted
    # directly to cover two registrations racing for one address.
    token = create_registration_token(holder.email, get_settings())

    response = await client.post(
        "/v1/auth/register",
        json={
            "registration_token": token.token,
            "password": PASSWORD,
            "full_name": "Duplicate",
        },
    )

    assert response.status_code == 409


async def test_registration_token_is_not_an_access_token(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    email = "typ@example.com"
    await client.post("/v1/auth/otp/send", json={"email": email})
    verify = await client.post(
        "/v1/auth/otp/verify",
        json={"email": email, "code": mailer.last_code()},
    )

    response = await client.get(
        "/v1/holders/me",
        headers=bearer(verify.json()["registration_token"]),
    )

    assert response.status_code == 401


async def test_login_with_email_or_did(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    by_email = await login(client, holder.email.upper())
    by_did = await login(client, holder.did)

    assert by_email.status_code == 200
    assert by_did.status_code == 200
    assert by_did.json()["holder_id"] == holder.holder_id


async def test_failed_logins_look_the_same(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    wrong_password = await login(client, holder.email, "wrong password")
    unknown = await login(client, "nobody@example.com")

    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.json()["error"]["code"] == "invalid_credentials"
    assert unknown.json()["error"]["code"] == "invalid_credentials"


async def test_repeated_failures_lock_the_account(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    for _ in range(get_settings().login_max_failed_attempts):
        await login(client, holder.email, "wrong password")

    response = await login(client, holder.email)

    assert response.status_code == 401


async def test_logout_revokes_the_token(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    logout = await client.post("/v1/auth/logout", headers=holder.headers)
    response = await client.get("/v1/holders/me", headers=holder.headers)

    assert logout.status_code == 204
    assert response.status_code == 401


async def test_change_password_ends_other_sessions_only(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    other_login = await login(client, holder.email)
    other_headers = bearer(other_login.json()["access_token"])

    response = await client.post(
        "/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=holder.headers,
    )
    current = await client.get("/v1/holders/me", headers=holder.headers)
    other = await client.get("/v1/holders/me", headers=other_headers)

    assert response.status_code == 204
    assert current.status_code == 200
    assert other.status_code == 401
    assert (await login(client, holder.email, NEW_PASSWORD)).status_code == 200


async def test_change_password_requires_current_password(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    response = await client.post(
        "/v1/auth/password/change",
        json={"current_password": "wrong", "new_password": NEW_PASSWORD},
        headers=holder.headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_current_password"


async def test_forgot_password_for_unknown_email_sends_nothing(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    response = await client.post(
        "/v1/auth/password/forgot", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 202
    assert mailer.sent == []


async def test_reset_password_is_single_use_and_ends_sessions(
    client: AsyncClient, mailer: RecordingMailer, holder: RegisteredHolder
) -> None:
    await client.post("/v1/auth/password/forgot", json={"email": holder.email})
    payload = {
        "token": reset_token_from(mailer),
        "new_password": NEW_PASSWORD,
    }

    first = await client.post("/v1/auth/password/reset", json=payload)
    second = await client.post("/v1/auth/password/reset", json=payload)
    old_session = await client.get("/v1/holders/me", headers=holder.headers)

    assert first.status_code == 204
    assert second.status_code == 400
    assert old_session.status_code == 401
    assert (await login(client, holder.email, NEW_PASSWORD)).status_code == 200


async def test_reset_unlocks_a_locked_account(
    client: AsyncClient, mailer: RecordingMailer, holder: RegisteredHolder
) -> None:
    for _ in range(get_settings().login_max_failed_attempts):
        await login(client, holder.email, "wrong password")
    await client.post("/v1/auth/password/forgot", json={"email": holder.email})

    await client.post(
        "/v1/auth/password/reset",
        json={"token": reset_token_from(mailer), "new_password": NEW_PASSWORD},
    )

    assert (await login(client, holder.email, NEW_PASSWORD)).status_code == 200


async def test_each_holder_gets_their_own_did(
    client: AsyncClient, mailer: RecordingMailer, holder: RegisteredHolder
) -> None:
    other = await register_holder(client, mailer, "second@example.com")

    assert other.did != holder.did


async def test_audit_log_records_sign_ins(
    client: AsyncClient, holder: RegisteredHolder
) -> None:
    await login(client, holder.email, "wrong password")

    response = await client.get(
        "/v1/holders/me/audit-logs", headers=holder.headers
    )

    actions = [entry["action"] for entry in response.json()["items"]]
    assert response.status_code == 200
    assert set(actions) == {"registered", "login_failed"}
