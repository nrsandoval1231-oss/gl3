import importlib.util
import pathlib
import uuid

import httpx
import pytest

from gridlens.intelligence import contact_suppressions as cs
from gridlens.jobs import alerts
from gridlens.settings import settings

CID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.mark.parametrize(
    "value",
    [
        "512-555-1234 x204",
        "512-555-1234 ext 204",
        "512-555-1234 ext. 204",
        "(512) 555-1234 extension 204",
        "tel:+1-512-555-1234;ext=204",
        "512-555-1234;ext=204",
        "+1 512 555 1234 X 204",
    ],
)
def test_phone_extension_canonicalizes_to_bare_number(value):
    bare = cs.global_method_suppression_key("phone", "512-555-1234")
    assert cs.global_method_suppression_key("phone", value) == bare
    assert cs.method_suppression_key(CID, None, "tel", value) == cs.method_suppression_key(
        CID, None, "phone", "5125551234"
    )


def test_phone_without_extension_keys_unchanged():
    assert cs._method_parts("phone", "+44 20 7946 0958") == ("phone", "+442079460958")
    assert cs._method_parts("phone", "1 (512) 555-1234") == ("phone", "5125551234")
    assert cs._method_parts("phone", "512-555-1234") == ("phone", "5125551234")


def test_ipv6_clients_share_a_64_bucket(monkeypatch):
    from gridlens import security

    monkeypatch.setattr(settings, "session_secret", "0123456789abcdef0123456789abcdef")
    a = security._bucket_id("client", "2001:db8:1:2::1")
    b = security._bucket_id("client", "2001:db8:1:2:ffff:ffff:ffff:ffff")
    c = security._bucket_id("client", "2001:db8:1:3::1")
    assert a == b != c
    assert security._bucket_id("client", "203.0.113.5") != security._bucket_id(
        "client", "203.0.113.6"
    )
    assert security._client_bucket_identity("203.0.113.5") == "203.0.113.5"
    assert security._client_bucket_identity("unknown") == "unknown"


def test_alert_failure_sends_only_exception_class(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send", lambda *args: sent.append(args))
    import gridlens.api.app as api

    def boom():
        raise RuntimeError("secret-dsn postgresql://u:pw@host/db")

    monkeypatch.setattr(api, "health", boom)
    monkeypatch.setattr(alerts, "spend_report", lambda: {"rows": []})
    with pytest.raises(SystemExit):
        alerts.main()
    title, body, urgent = sent[0]
    assert body == "RuntimeError" and "secret" not in body and urgent
    assert httpx  # keep import used for parity with sibling tests


def test_readiness_uses_cheap_probe(monkeypatch):
    import gridlens.api.app as api

    statements = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, stmt):
            statements.append(str(stmt).lower())
            return self

        def first(self):
            return None

    monkeypatch.setattr(api, "SessionLocal", FakeSession)
    assert api.runtime_readiness() == {"readiness": "READY"}
    assert "count" not in statements[0] and "limit" in statements[0]

    class Broken(FakeSession):
        def execute(self, stmt):
            raise RuntimeError("down")

    monkeypatch.setattr(api, "SessionLocal", Broken)
    with pytest.raises(api.HTTPException) as err:
        api.runtime_readiness()
    assert err.value.status_code == 503


def _guard():
    path = pathlib.Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("_gl_conftest_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.test_database_guard_error


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@127.0.0.1:5432/gridlens_test",
        "postgresql+psycopg://u:p@localhost/x_test",
        "postgresql+psycopg://u:p@[::1]/x_test",
        "",
    ],
)
def test_database_guard_accepts_loopback_test_databases(url):
    assert _guard()(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@db.example.com/gridlens_test",
        "postgresql+psycopg://u:p@127.0.0.1/gridlens",
        "postgresql+psycopg://u:p@127.0.0.1/",
        "postgresql+psycopg://u:p@/gridlens_test",
        "not a url",
    ],
)
def test_database_guard_refuses_unsafe_targets(url):
    assert _guard()(url)
