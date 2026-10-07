import time

import pytest
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
