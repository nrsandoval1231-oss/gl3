from uuid import uuid4

from fastapi.testclient import TestClient

from gridlens.api.app import app


def test_enrichment_routes_require_authentication():
    client = TestClient(app)
    identity = uuid4()
    for route in (
        f"/api/companies/{identity}/graph",
        f"/api/companies/{identity}/contact-assertions",
        f"/api/projects/{identity}/power-enrichment",
    ):
        assert client.get(route).status_code == 401
    assert (
        client.post(f"/api/contact-assertions/{identity}/corrections", json={}).status_code == 404
    )
