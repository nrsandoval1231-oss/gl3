import pytest
from fastapi.testclient import TestClient

from gridlens.api.app import app


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/editorial/candidates"),
        ("GET", "/api/editorial/sync"),
        ("GET", "/api/editorial/review"),
        ("GET", "/api/editorial/clearance/00000000-0000-0000-0000-000000000001"),
        ("POST", "/api/editorial/review/00000000-0000-0000-0000-000000000001"),
        ("POST", "/api/editorial/assessment/00000000-0000-0000-0000-000000000001"),
    ],
)
def test_editorial_routes_never_allow_anonymous_access(method, path):
    client = TestClient(app)
    response = client.request(method, path, **({"json": {}} if method == "POST" else {}))
    assert response.status_code == 401
