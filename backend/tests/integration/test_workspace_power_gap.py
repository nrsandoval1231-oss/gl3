"""Workspace API preserves only current, qualified Lead power gaps."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

pytest_plugins = ["test_pursuit_workspace"]


def test_workspace_power_gap_is_null_for_unqualified_needs(saved_db):
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.api.app import OpportunityOut
    from gridlens.intelligence.saved_browse import rebuild
    from gridlens.security import token_for

    fields = OpportunityOut.model_fields
    assert fields["qualified_remaining_gap"].annotation is not None
    assert fields["qualification_version"].annotation is not None
    assert fields["qualified_remaining_gap"].default is None
    assert fields["qualification_version"].default is None

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get("/api/opportunities/workspace")
    assert response.status_code == 200, response.text
    assert all(
        item["qualified_remaining_gap"] is None and item["qualification_version"] is None
        for item in response.json()["items"]
    )
