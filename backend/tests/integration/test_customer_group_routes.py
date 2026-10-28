"""Authenticated HTTP contract for the grouped opportunity endpoints."""

from datetime import UTC, datetime
from importlib import import_module

from fastapi.testclient import TestClient

from gridlens.intelligence.saved_browse import rebuild
from gridlens.security import token_for
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


def test_customer_group_routes_validate_queries_and_cohort_tokens(saved_db, monkeypatch):
    from test_saved_browse import seed

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")
    client = TestClient(api.app, base_url="https://testserver")

    assert client.get("/api/opportunities/groups").status_code == 401
    assert client.get("/api/opportunities/groups/example/projects").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))

    parent = client.get(
        "/api/opportunities/groups",
        params={"search": "Synthetic", "sector": "all", "limit": 1, "sort": "priority"},
    )
    assert parent.status_code == 200, parent.text
    parent_payload = parent.json()
    assert parent_payload["items"]
    assert parent_payload["total"] >= 2
    next_parent = client.get(
        "/api/opportunities/groups",
        params={
            "search": "Synthetic",
            "sector": "all",
            "limit": 1,
            "offset": 1,
            "cohort_token": parent_payload["cohort_token"],
        },
    )
    assert next_parent.status_code == 200, next_parent.text
    assert len(next_parent.json()["items"]) == 1

    group_id = parent_payload["items"][0]["id"]
    child_path = f"/api/opportunities/groups/{group_id}/projects"
    child_params = {
        "search": "Synthetic",
        "sector": "all",
        "limit": 10,
        "sort": "priority",
        "parent_cohort_token": parent_payload["cohort_token"],
    }
    child = client.get(child_path, params=child_params)
    assert child.status_code == 200, child.text
    assert child.json()["items"]

    opened = client.get(f"/api/opportunities/groups/{group_id}/open")
    assert opened.status_code == 200, opened.text
    opened_payload = opened.json()
    assert opened_payload["group"] == parent_payload["items"][0]
    assert opened_payload["projects"]["items"]
    child_cohort = opened_payload["projects"]["cohort_token"]
    assert opened_payload["parent_cohort_token"] == child_cohort.split(".group.")[0]
    assert opened_payload["generation"] == opened_payload["projects"]["generation"]

    missing_parent = client.get(child_path, params={"sector": "all"})
    assert missing_parent.status_code == 422
    stale_parent = client.get(child_path, params={**child_params, "parent_cohort_token": "stale"})
    assert stale_parent.status_code == 409

    invalid_requests = (
        ("/api/opportunities/groups", {"sector": "unsupported"}),
        ("/api/opportunities/groups", {"search": "x" * 251}),
        ("/api/opportunities/groups", {"geography": "Dallas"}),
        (child_path, {**child_params, "tier": "Signal"}),
        (child_path, {**child_params, "search": "x" * 251}),
        (f"/api/opportunities/groups/{group_id}/open", {"offset": 1}),
        (f"/api/opportunities/groups/{group_id}/open", {"cohort_token": "stale"}),
    )
    for path, params in invalid_requests:
        response = client.get(path, params=params)
        assert response.status_code == 422, (path, response.text)
