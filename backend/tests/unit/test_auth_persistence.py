import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from gridlens.api.app import app
from gridlens.persistence.models import AuthLoginBucket, AuthSession
from gridlens.security import client_ip, consume_login_attempt, create_session, valid_token
from gridlens.settings import settings


def _request(peer: str, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 1234),
            "server": ("gridlens.example", 443),
        }
    )


def test_session_revocation_rotation_expiry_and_digest(monkeypatch):
    engine = create_engine(settings.test_database_url)
    assert engine.url.database != create_engine(settings.database_url).url.database
    AuthSession.__table__.create(engine, checkfirst=True)
    AuthLoginBucket.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("gridlens.api.app.SessionLocal", factory)
    monkeypatch.setattr("gridlens.api.app.check_password", lambda _password: True)
    monkeypatch.setattr(settings, "trusted_origins", "https://gridlens.example.com")
    monkeypatch.setattr(settings, "cookie_secure", True)
    with factory.begin() as session:
        session.execute(AuthSession.__table__.delete())
        session.execute(AuthLoginBucket.__table__.delete())

    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"password": "test"},
        headers={"origin": "https://gridlens.example.com"},
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert "secure" in cookie
    token = client.cookies.get("gridlens_session")
    assert token and len(token) >= 43
    client.cookies.set("gridlens_session", token)
    with factory() as session:
        stored = session.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
        assert stored is not None
        assert stored.token_digest != token
        assert stored.credential_fingerprint
    assert client.get("/api/auth/session").json() == {"authenticated": True}
    assert (
        client.post(
            "/api/auth/logout", headers={"origin": "https://gridlens.example.com"}
        ).status_code
        == 200
    )
    client.cookies.set("gridlens_session", token)
    assert client.get("/api/health").status_code == 401

    second, _ = create_session()
    original_hash = settings.app_password_hash
    monkeypatch.setattr(settings, "app_password_hash", original_hash + "rotated")
    assert not valid_token(second)
    monkeypatch.setattr(settings, "app_password_hash", original_hash)
    original_secret = settings.session_secret
    monkeypatch.setattr(settings, "session_secret", original_secret + "rotated")
    assert not valid_token(second)
    monkeypatch.setattr(settings, "session_secret", original_secret)
    with factory.begin() as session:
        expired = session.get(AuthSession, hashlib.sha256(second.encode()).hexdigest())
        assert expired is not None
        expired.expires_at = datetime.now(UTC) - timedelta(days=8)
    assert not valid_token(second)
    create_session()
    with factory() as session:
        assert session.get(AuthSession, hashlib.sha256(second.encode()).hexdigest()) is None
    engine.dispose()


def test_login_limit_is_atomic_persistent_and_bounded(monkeypatch):
    engine = create_engine(settings.test_database_url)
    AuthLoginBucket.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("gridlens.api.app.SessionLocal", factory)
    monkeypatch.setattr(settings, "login_client_limit", 3)
    monkeypatch.setattr(settings, "login_global_limit", 5)
    monkeypatch.setattr(settings, "login_client_bucket_cap", 2)
    with factory.begin() as session:
        session.execute(AuthLoginBucket.__table__.delete())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: consume_login_attempt("198.51.100.11"), range(8)))
    assert sum(results) == 3
    restarted_factory = sessionmaker(
        create_engine(settings.test_database_url), expire_on_commit=False
    )
    monkeypatch.setattr("gridlens.api.app.SessionLocal", restarted_factory)
    assert consume_login_attempt("198.51.100.11") is False  # State survived a new factory.
    consume_login_attempt("198.51.100.12")
    consume_login_attempt("198.51.100.13")
    with factory.begin() as session:
        clients = session.scalar(
            select(func.count())
            .select_from(AuthLoginBucket)
            .where(AuthLoginBucket.scope == "client")
        )
        assert clients <= 3  # Two ordinary keys plus the single overflow key.
        for expired in session.scalars(select(AuthLoginBucket)).all():
            expired.window_started_at = datetime.now(UTC) - timedelta(minutes=2)
    monkeypatch.setattr(settings, "login_global_limit", 10)
    assert consume_login_attempt("198.51.100.14") is True
    engine.dispose()


def test_global_login_limit_is_shared_across_distinct_clients(monkeypatch):
    engine = create_engine(settings.test_database_url)
    AuthLoginBucket.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("gridlens.api.app.SessionLocal", factory)
    monkeypatch.setattr(settings, "login_client_limit", 10)
    monkeypatch.setattr(settings, "login_global_limit", 5)
    monkeypatch.setattr(settings, "login_client_bucket_cap", 100)
    with factory.begin() as session:
        session.execute(AuthLoginBucket.__table__.delete())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda index: consume_login_attempt(f"198.51.100.{index + 20}"), range(8))
        )
    assert sum(results) == 5
    restarted_factory = sessionmaker(create_engine(settings.test_database_url))
    monkeypatch.setattr("gridlens.api.app.SessionLocal", restarted_factory)
    assert consume_login_attempt("198.51.100.99") is False
    engine.dispose()


def test_proxy_headers_are_trusted_only_from_configured_hops(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8,192.0.2.10/32")
    spoofed = _request(
        "198.51.100.2",
        [(b"x-forwarded-for", b"203.0.113.8"), (b"forwarded", b"for=203.0.113.8")],
    )
    assert client_ip(spoofed) == "198.51.100.2"
    mapped = _request("::ffff:198.51.100.2", [(b"x-forwarded-for", b"203.0.113.8")])
    assert client_ip(mapped) == "198.51.100.2"
    one_hop = _request("10.1.2.3", [(b"x-forwarded-for", b"203.0.113.8")])
    assert client_ip(one_hop) == "203.0.113.8"
    two_hop = _request("10.1.2.3", [(b"x-forwarded-for", b"203.0.113.8, 192.0.2.10")])
    assert client_ip(two_hop) == "203.0.113.8"
    other_client = _request("10.1.2.3", [(b"x-forwarded-for", b"198.51.100.44, 192.0.2.10")])
    assert client_ip(other_client) == "198.51.100.44"
    assert client_ip(other_client) != client_ip(two_hop)
    malformed = _request("10.1.2.3", [(b"x-forwarded-for", b"203.0.113.8, nope")])
    assert client_ip(malformed) == "10.1.2.3"
    oversized = _request("10.1.2.3", [(b"x-forwarded-for", b"1" * 2049)])
    assert client_ip(oversized) == "10.1.2.3"


def test_login_rejects_untrusted_origin(monkeypatch):
    monkeypatch.setattr("gridlens.api.app.consume_login_attempt", lambda _ip: True)
    monkeypatch.setattr("gridlens.api.app.check_password", lambda _password: True)
    response = TestClient(app).post(
        "/api/auth/login", json={"password": "test"}, headers={"origin": "https://evil.example"}
    )
    assert response.status_code == 403
