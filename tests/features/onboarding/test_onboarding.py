import json
import uuid
from typing import Any

import httpx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.connector import ConnectorClient
from app.core.models import utc_now
from app.features.onboarding.models import (
    PROFILE_UPDATED_OPERATION,
    REGISTERED_OPERATION,
    PendingInvite,
    RegistrationReport,
    ReportStatus,
)
from app.features.onboarding.service import RegistrationReportService
from tests.conftest import (
    FakeConnector,
    RecordingMailer,
    RegisteredHolder,
    register_holder,
)
from tests.features.notifications.helpers import post_event

OPERATIONS_PATH = "/v1/holders/operations"


def invite_event(
    holder_email: str, inviter_name: str | None = "Example University"
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "event": "holder.invited",
        "created_at": "2026-10-28T10:00:00+00:00",
        "data": {
            "source_code": "dcs-india",
            "holder_email": holder_email,
            "inviter_name": inviter_name,
        },
    }


def operation_answer(
    *items: tuple[str, int],
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "items": [
                {
                    "source_code": source_code,
                    "status_code": status_code,
                    "ok": 200 <= status_code < 300,
                    "data": None,
                    "message": None,
                }
                for source_code, status_code in items
            ]
        },
    )


async def list_reports(
    session_factory: async_sessionmaker[AsyncSession],
    operation: str = REGISTERED_OPERATION,
) -> list[RegistrationReport]:
    async with session_factory() as session:
        rows = await session.scalars(
            select(RegistrationReport).where(
                RegistrationReport.operation == operation
            )
        )
        return list(rows.all())


def sent_bodies(connector: FakeConnector) -> dict[str, dict[str, Any]]:
    """Return the last operation body sent, keyed by operation name."""
    bodies = [json.loads(request.content) for request in connector.requests]
    return {body["operation"]: body for body in bodies}


async def run_reports(
    session_factory: async_sessionmaker[AsyncSession],
    connector: FakeConnector,
) -> int:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(connector.handle)
    )
    async with session_factory() as session:
        service = RegistrationReportService(
            session,
            get_settings(),
            ConnectorClient(http_client, get_settings()),
        )
        ran = await service.deliver_due(batch_size=10)
    await http_client.aclose()
    return ran


async def test_invite_for_new_email_waits_until_registration(
    client: AsyncClient,
    mailer: RecordingMailer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await post_event(client, invite_event("New@Example.com"))

    async with session_factory() as session:
        invites = (await session.scalars(select(PendingInvite))).all()
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(invites) == 1
    # Only a keyed hash of the email is stored.
    assert "new@example.com" not in invites[0].email_key

    holder = await register_holder(client, mailer, "new@example.com")

    inbox = await client.get("/v1/notifications", headers=holder.headers)
    [item] = inbox.json()["items"]
    assert item["notification_type"] == "issuer_invitation"
    assert item["message"] == (
        "Example University invited you to receive credentials."
    )
    assert item["extra_metadata"] == {"source_code": "dcs-india"}
    async with session_factory() as session:
        assert (await session.scalars(select(PendingInvite))).all() == []
    [report] = await list_reports(session_factory)
    assert report.source_code is None
    assert report.status == ReportStatus.PENDING.value


async def test_registration_without_invites_still_queues_a_report(
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [report] = await list_reports(session_factory)
    [profile_report] = await list_reports(
        session_factory, PROFILE_UPDATED_OPERATION
    )

    assert report.source_code is None
    assert profile_report.source_code is None


async def test_invite_for_existing_holder_notifies_and_reports_to_source(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await post_event(
        client, invite_event(holder.email, inviter_name=None)
    )

    inbox = await client.get("/v1/notifications", headers=holder.headers)
    assert response.json() == {"status": "accepted"}
    assert inbox.json()["items"][0]["message"] == (
        "An issuer invited you to receive credentials."
    )
    reports = await list_reports(session_factory)
    profile_reports = await list_reports(
        session_factory, PROFILE_UPDATED_OPERATION
    )
    assert sorted(str(report.source_code) for report in reports) == [
        "None",
        "dcs-india",
    ]
    # The inviting DCS also gets the holder's own name and contact.
    assert sorted(str(report.source_code) for report in profile_reports) == [
        "None",
        "dcs-india",
    ]


async def test_report_is_sent_as_the_registered_operation(
    holder: RegisteredHolder,
    connector: FakeConnector,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connector.handlers[OPERATIONS_PATH] = lambda request: operation_answer(
        ("dcs-india", 200), ("dcs-edu", 404)
    )

    ran = await run_reports(session_factory, connector)

    [report] = await list_reports(session_factory)
    body = sent_bodies(connector)[REGISTERED_OPERATION]
    assert ran == 2
    assert body["holder_email"] == holder.email
    assert body["source_code"] is None
    assert body["body"] is None
    # A DCS that no longer knows the holder (404) has nothing to update.
    assert report.status == ReportStatus.DONE.value


async def test_profile_report_sends_the_current_name_and_contact(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connector.handlers[OPERATIONS_PATH] = lambda request: operation_answer(
        ("dcs-india", 200)
    )
    # Changed after the report was queued: the report reads the holder
    # when it is sent, so the DCS gets the new values.
    await client.put(
        "/v1/holder/update",
        json={"name": "Renamed Holder", "contact": "+9876543210"},
        headers=holder.headers,
    )

    await run_reports(session_factory, connector)

    body = sent_bodies(connector)[PROFILE_UPDATED_OPERATION]
    [report] = await list_reports(session_factory, PROFILE_UPDATED_OPERATION)
    assert body["source_code"] is None
    assert body["body"] == {"name": "Renamed Holder", "mobile": "+9876543210"}
    assert report.status == ReportStatus.DONE.value


async def test_profile_change_queues_one_report_while_one_is_waiting(
    client: AsyncClient,
    holder: RegisteredHolder,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for name in ("First Rename", "Second Rename"):
        await client.put(
            "/v1/holder/update", json={"name": name}, headers=holder.headers
        )

    reports = await list_reports(session_factory, PROFILE_UPDATED_OPERATION)

    # The sign-up report is still pending and will carry both renames.
    assert len(reports) == 1


async def test_profile_change_after_delivery_queues_a_new_report(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connector.handlers[OPERATIONS_PATH] = lambda request: operation_answer(
        ("dcs-india", 200)
    )
    await run_reports(session_factory, connector)

    await client.put(
        "/v1/holder/update", json={"name": "Renamed"}, headers=holder.headers
    )
    await client.put(
        "/v1/holder/update",
        json={"contact": "+9876543210"},
        headers=holder.headers,
    )

    reports = await list_reports(session_factory, PROFILE_UPDATED_OPERATION)
    assert sorted(report.status for report in reports) == [
        ReportStatus.DONE.value,
        ReportStatus.PENDING.value,
    ]


async def test_unchanged_profile_queues_no_report(
    client: AsyncClient,
    holder: RegisteredHolder,
    connector: FakeConnector,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connector.handlers[OPERATIONS_PATH] = lambda request: operation_answer(
        ("dcs-india", 200)
    )
    await run_reports(session_factory, connector)
    profile = (await client.get("/v1/holder", headers=holder.headers)).json()[
        "data"
    ]

    await client.put(
        "/v1/holder/update",
        json={"name": profile["name"]},
        headers=holder.headers,
    )

    reports = await list_reports(session_factory, PROFILE_UPDATED_OPERATION)
    assert [report.status for report in reports] == [ReportStatus.DONE.value]


async def test_unavailable_source_is_retried_later(
    holder: RegisteredHolder,
    connector: FakeConnector,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connector.handlers[OPERATIONS_PATH] = lambda request: operation_answer(
        ("dcs-india", 200), ("dcs-edu", 502)
    )

    await run_reports(session_factory, connector)

    [report] = await list_reports(session_factory)
    assert report.status == ReportStatus.PENDING.value
    assert report.attempts == 1
    assert report.last_error == "no answer from dcs-edu"
    assert report.next_attempt_at > utc_now()


async def test_unreachable_connector_is_retried_later(
    holder: RegisteredHolder,
    connector: FakeConnector,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connector.handlers[OPERATIONS_PATH] = lambda request: httpx.Response(503)

    await run_reports(session_factory, connector)

    [report] = await list_reports(session_factory)
    assert report.status == ReportStatus.PENDING.value
    assert report.attempts == 1


async def test_unlinked_source_fails_the_report(
    holder: RegisteredHolder,
    connector: FakeConnector,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # No handler: the fake connector answers 404 like an unlinked source.
    await run_reports(session_factory, connector)

    [report] = await list_reports(session_factory)
    assert report.status == ReportStatus.FAILED.value
    assert report.last_error == "Not found."
