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
os.environ["CREDENTIAL_EMAIL_HOURLY_LIMIT"] = "2"

import httpx  # noqa: E402
import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

# Model modules are imported so Base.metadata knows every table.
import app.features.audit.models  # noqa: E402, F401
import app.features.auth.models  # noqa: E402, F401
import app.features.devices.models  # noqa: E402, F401
import app.features.dids.models  # noqa: E402, F401
import app.features.holders.models  # noqa: E402, F401
import app.features.notifications.models  # noqa: E402, F401
from app.core.config import get_settings  # noqa: E402
from app.core.connector import ConnectorClient, get_connector_client  # noqa: E402
from app.core.database import Base, get_db_session  # noqa: E402
from app.core.email import OutgoingEmail, get_email_sender  # noqa: E402
from app.core.storage import get_storage  # noqa: E402
from app.main import create_app  # noqa: E402

PASSWORD = "correct horse battery staple"
ConnectorHandler = Callable[[httpx.Request], httpx.Response]


class MemoryStorage:
    """Object storage kept in a dict."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = (content, content_type)

    async def url_for(self, key: str) -> str:
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
    holder_id: str
    did: str
    access_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # StaticPool keeps one connection open, so every session sees the
    # same in-memory database for the duration of the test.
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
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


async def register_holder(
    client: AsyncClient,
    mailer: RecordingMailer,
    email: str = "holder@example.com",
) -> RegisteredHolder:
    """Run OTP send, verify, and register; return the new holder."""
    await client.post("/v1/auth/otp/send", json={"email": email})
    verify_response = await client.post(
        "/v1/auth/otp/verify",
        json={"email": email, "code": mailer.last_code()},
    )
    registration_token = verify_response.json()["registration_token"]
    register_response = await client.post(
        "/v1/auth/register",
        json={
            "registration_token": registration_token,
            "password": PASSWORD,
            "full_name": "Test Holder",
        },
    )
    assert register_response.status_code == 201, register_response.text
    body = register_response.json()
    return RegisteredHolder(
        email=email,
        password=PASSWORD,
        holder_id=body["holder_id"],
        did=body["did"],
        access_token=body["access_token"],
    )


@pytest.fixture
async def holder(
    client: AsyncClient, mailer: RecordingMailer
) -> RegisteredHolder:
    return await register_holder(client, mailer)
