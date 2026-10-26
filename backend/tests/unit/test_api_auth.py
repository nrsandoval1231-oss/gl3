from datetime import UTC, datetime

from fastapi.testclient import TestClient

from gridlens.api.app import app, chicago_today


def test_private_api_routes_reject_missing_session():
    client = TestClient(app)
    for path in ("/api/health", "/api/opportunities", "/api/changes"):
        response = client.get(path)
        assert response.status_code == 401
    response = client.get("/api/search", params={"q": "Texas"})
    assert response.status_code == 401


def test_private_api_routes_reject_oversized_session_expiry_without_server_error():
    client = TestClient(app)
    client.cookies.set("gridlens_session", "9" * 4500 + ".x")
    response = client.get("/api/health")
    assert response.status_code == 401


def test_change_day_boundary_uses_chicago_calendar_date():
    # 02:00 UTC is still 21:00 on the prior date in Chicago during daylight time.
    instant = datetime(2026, 9, 26, 2, 0, tzinfo=UTC)
    assert chicago_today(instant).isoformat() == "2026-09-25"


def test_openapi_document_requires_an_authenticated_request():
    client = TestClient(app)
    assert client.get("/openapi.json").status_code == 401
