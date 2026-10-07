import asyncio
import time

import pytest
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from gridlens.persistence.models import AuthSession
from gridlens.security import token_for, valid_token
from gridlens.settings import settings


@pytest.fixture
def auth_session_store(monkeypatch):
    engine = create_engine(settings.test_database_url)
    AuthSession.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("gridlens.api.app.SessionLocal", factory)
    with factory.begin() as session:
        session.execute(AuthSession.__table__.delete())
    yield
    engine.dispose()


def test_session_token_is_opaque_persisted_and_expiring(auth_session_store):
    token = token_for(int(time.time()) + 60)
    assert valid_token(token)
    assert not valid_token(token + "x")
    assert not valid_token(token_for(int(time.time()) - 1))


def test_session_token_rejects_oversized_expiry_before_integer_conversion():
    assert not valid_token("9" * 4500 + "." + "0" * 64)


def test_session_token_rejects_non_ascii_expiry_digits():
    assert not valid_token("².0000000000000000000000000000000000000000000000000000000000000000")


def test_session_token_rejects_non_hex_signature():
    assert not valid_token("9999999999." + "é" * 64)


def test_installed_uvicorn_config_ignores_forwarded_peer_headers_when_disabled():
    observed_clients = []

    async def app(scope, receive, send):
        observed_clients.append(scope["client"])

    config = uvicorn.Config(app, proxy_headers=False)
    config.load()

    async def invoke():
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await config.loaded_app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "root_path": "",
                "headers": [(b"x-forwarded-for", b"198.51.100.99")],
                "client": ("127.0.0.1", 1234),
                "server": ("127.0.0.1", 8000),
            },
            receive,
            send,
        )
        return messages

    asyncio.run(invoke())

    assert config.proxy_headers is False
    assert observed_clients == [("127.0.0.1", 1234)]
