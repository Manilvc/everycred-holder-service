"""Shared pytest fixtures."""

import json
import os
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

# Settings are read when app.main is imported, so the environment must
# be prepared first. Values are assigned (not defaulted) so a developer's
# .env file cannot change test behaviour. The MySQL URL is never
# connected to: the session dependency is replaced with SQLite below.
os.environ["DATABASE_URL"] = "mysql+aiomysql://test:test@127.0.0.1:3306/test"
os.environ["JWT_SECRET_KEY"] = "test-signing-key-" + "x" * 32
os.environ["TOKEN_HASH_SECRET"] = "test-token-hash-" + "y" * 32
os.environ["CONNECTOR_BASE_URL"] = "http://connector.test"
os.environ["CONNECTOR_API_KEY"] = "ecc_000000000000_test-connector-key"
os.environ["CONNECTOR_WEBHOOK_SECRET"] = "test-webhook-secret-" + "z" * 32
os.environ["LOG_JSON"] = "false"
os.environ["ENVIRONMENT"] = "local"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["EMAIL_BACKEND"] = "console"
os.environ["OTP_RESEND_COOLDOWN_SECONDS"] = "60"
os.environ["LOGIN_MAX_FAILED_ATTEMPTS"] = "3"
os.environ["OTP_TTL_MINUTES"] = "2"
os.environ["OTP_MAX_ATTEMPTS"] = "3"
os.environ["VERIFIER_BASE_URL"] = "https://verifier.example.com/"

import httpx  # noqa: E402
import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

# Model modules are imported so Base.metadata knows every table.
import app.features.audit.models  # noqa: E402, F401
import app.features.auth.models  # noqa: E402, F401
import app.features.credentials.models  # noqa: E402, F401
import app.features.devices.models  # noqa: E402, F401
import app.features.dids.models  # noqa: E402, F401
import app.features.holders.models  # noqa: E402, F401
import app.features.notifications.models  # noqa: E402, F401
import app.features.onboarding.models  # noqa: E402, F401
from app.core.config import get_settings  # noqa: E402
from app.core.connector import ConnectorClient, get_connector_client  # noqa: E402
from app.core.database import Base, get_db_session  # noqa: E402
from app.core.email import OutgoingEmail, get_email_sender  # noqa: E402
from app.core.storage import get_storage  # noqa: E402
from app.main import create_app  # noqa: E402

PASSWORD = "CorrectHorse9!"
ConnectorHandler = Callable[[httpx.Request], httpx.Response]


class MemoryStorage:
    """Object storage kept in a dict."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.url_ttls: dict[str, int | None] = {}

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = (content, content_type)

    async def url_for(self, key: str, ttl_seconds: int | None = None) -> str:
        self.url_ttls[key] = ttl_seconds
        return f"https://files.example.com/{key}?signature=test"


class RecordingMailer:
    """Email sender that keeps every message instead of sending it."""

    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []

    async def send(self, email: OutgoingEmail) -> None:
        self.sent.append(email)

    def last_code(self) -> str:
        match = re.search(r"\b(\d{6})\b", self.sent[-1].body)
        assert match, "no code in the last email"
        return match.group(1)


@dataclass
class FakeConnector:
    """Routes connector calls to per-path handlers and records them."""

    handlers: dict[str, ConnectorHandler] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.handlers.get(request.url.path)
        if handler is None:
            return httpx.Response(
                404,
                json={"error": {"code": "not_found", "message": "Not found."}},
            )
        return handler(request)

    def last_body(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


@dataclass
class RegisteredHolder:
    """A holder created through the public registration flow."""

    email: str
    password: str
    holder_id: int
    uuid: str
    did: str
    access_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def _enforce_foreign_keys(
    dbapi_connection: Any, connection_record: Any
) -> None:
    # SQLite ignores foreign keys unless asked. MySQL always enforces
    # them, so tests must too, or rows inserted in the wrong order pass
    # here and fail in production.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # StaticPool keeps one connection open, so every session sees the
    # same in-memory database for the duration of the test.
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    event.listen(engine.sync_engine, "connect", _enforce_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def connector() -> FakeConnector:
    return FakeConnector()


@pytest.fixture
def app(
    session_factory: async_sessionmaker[AsyncSession],
    storage: MemoryStorage,
    mailer: RecordingMailer,
    connector: FakeConnector,
) -> FastAPI:
    application = create_app()

    async def get_test_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def get_test_connector() -> ConnectorClient:
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(connector.handle)
        )
        return ConnectorClient(http_client, get_settings())

    application.dependency_overrides[get_db_session] = get_test_db_session
    application.dependency_overrides[get_storage] = lambda: storage
    application.dependency_overrides[get_email_sender] = lambda: mailer
    application.dependency_overrides[get_connector_client] = get_test_connector
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # LifespanManager runs startup and shutdown so lifespan state is
    # populated exactly as in production.
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client


async def verify_email(
    client: AsyncClient, mailer: RecordingMailer, email: str
) -> None:
    """Send and verify a registration OTP for ``email``."""
    send_response = await client.post(
        "/v1/wallet/holder/otp/send",
        json={"email": email, "otp_type": "email"},
    )
    assert send_response.status_code == 200, send_response.text
    verify_response = await client.post(
        "/v1/wallet/holder/otp/verify",
        json={
            "email": email,
            "otp_code": mailer.last_code(),
            "otp_type": "email",
        },
    )
    assert verify_response.status_code == 200, verify_response.text


async def login(
    client: AsyncClient, email: str, password: str = PASSWORD
) -> str:
    """Sign in and return the access token."""
    response = await client.post(
        "/v1/holder/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["token"]


async def register_holder(
    client: AsyncClient,
    mailer: RecordingMailer,
    email: str = "holder@example.com",
) -> RegisteredHolder:
    """Run the wallet's OTP, register, and login calls for a new holder."""
    await verify_email(client, mailer, email)
    register_response = await client.post(
        "/v1/holder/register",
        json={
            "name": "Test Holder",
            "email": email,
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
    )
    assert register_response.status_code == 201, register_response.text
    token = await login(client, email)
    profile = await client.get(
        "/v1/holder", headers={"Authorization": f"Bearer {token}"}
    )
    data = profile.json()["data"]
    return RegisteredHolder(
        email=email,
        password=PASSWORD,
        holder_id=data["id"],
        uuid=data["uuid"],
        did=data["did"],
        access_token=token,
    )


@pytest.fixture
async def holder(
    client: AsyncClient, mailer: RecordingMailer
) -> RegisteredHolder:
    return await register_holder(client, mailer)
