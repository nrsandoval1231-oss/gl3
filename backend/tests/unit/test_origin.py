from fastapi.testclient import TestClient

from gridlens.api.app import app
from gridlens.settings import settings


def test_login_rejects_untrusted_origin():
    response = TestClient(app).post(
        "/api/auth/login",
        json={"password": "not-the-local-password"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_login_allows_configured_frontend_origin_to_reach_password_check(monkeypatch):
    monkeypatch.setattr(settings, "trusted_origins", "http://127.0.0.1:5173")
    response = TestClient(app).post(
        "/api/auth/login",
        json={"password": "not-the-local-password"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 401
