from fastapi.testclient import TestClient

from gridlens.api.app import app

RETIRED_OPERATOR_ROUTES = {
    ("GET", "/api/needs/{need_id}/facts"),
    ("POST", "/api/needs/{need_id}/facts"),
    ("POST", "/api/needs/{need_id}/facts/{fact_version_id}/decision"),
    ("GET", "/api/needs/{need_id}/workflow-status"),
    ("POST", "/api/needs/{need_id}/workflow-status"),
    ("POST", "/api/pursuits/{pursuit_id}/notes"),
    ("POST", "/api/projects/{project_id}/buying-chain/{claim_id}/corrections"),
    ("POST", "/api/customer-account-memberships/{membership_id}/retractions"),
    ("POST", "/api/signals/decisions/adjudicate"),
    ("POST", "/api/opportunities/workspace/changes/review"),
    ("POST", "/api/intelligence/needs/{need_id}/feedback"),
    ("POST", "/api/commercial/triage/evaluate"),
    ("POST", "/api/commercial/triage/{need_id}/research"),
    ("GET", "/api/commercial/triage/{need_id}/research"),
    ("POST", "/api/refresh"),
    ("POST", "/api/sources/{source_id}/enabled"),
    ("POST", "/api/power-needs/{need_id}/brief"),
    ("POST", "/api/power-needs/{need_id}/title"),
    ("POST", "/api/projects/{project_id}/buying-chain/enrich"),
    ("POST", "/api/pursuits/refresh"),
    ("POST", "/api/commercial/triage/{need_id}/autonomous-research"),
    ("POST", "/api/intelligence/needs/{need_id}/jobs"),
    ("POST", "/api/intelligence/needs/{need_id}/evidence/{evidence_id}/ocr"),
    ("POST", "/api/intelligence/needs/{need_id}/evidence/{evidence_id}/ocr-followon"),
    ("POST", "/api/intelligence/needs/{need_id}/jobs/{job_id}/cancel"),
    ("POST", "/api/intelligence/needs/{need_id}/jobs/{job_id}/retry"),
    ("POST", "/api/intelligence/needs/{need_id}/watches"),
}


def test_operator_workflow_routes_are_removed_from_public_api_and_openapi():
    registered = {
        (method, route.path) for route in app.routes for method in getattr(route, "methods", ())
    }
    assert not (registered & RETIRED_OPERATOR_ROUTES)

    paths = app.openapi()["paths"]
    for method, path in RETIRED_OPERATOR_ROUTES:
        assert method.lower() not in paths.get(path, {})
    assert "CallFactDraftBody" not in app.openapi()["components"]["schemas"]
    assert "NeedWorkflowStatusBody" not in app.openapi()["components"]["schemas"]


def test_autonomous_research_request_and_status_routes_remain_available():
    registered = {
        (method, route.path) for route in app.routes for method in getattr(route, "methods", ())
    }
    assert ("GET", "/api/commercial/triage/{need_id}/autonomous-research") in registered
    assert ("GET", "/api/search") in registered


def test_historical_operator_evidence_tables_remain_intact():
    from gridlens.persistence.models import Base

    assert "call_fact_versions" in Base.metadata.tables
    assert "call_fact_decisions" in Base.metadata.tables
    assert "need_workflow_status_events" in Base.metadata.tables
    assert "pursuit_call_notes" in Base.metadata.tables


def test_unified_search_requires_a_session():
    response = TestClient(app).get("/api/search", params={"q": "Taylor"})
    assert response.status_code == 401


def test_retired_fact_write_route_is_not_dispatchable():
    response = TestClient(app).post("/api/needs/00000000-0000-0000-0000-000000000001/facts")
    assert response.status_code == 404
