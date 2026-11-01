"""Representative-scale customer group route regression coverage."""

from datetime import UTC, datetime
from importlib import import_module
from uuid import UUID

from fastapi.testclient import TestClient
from rollup_scale_fixture import seed_scale_corpus
from sqlalchemy import event, func, select

from gridlens.persistence.models import PowerNeed, Project
from gridlens.security import token_for
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


def _client(saved_db, monkeypatch):
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", saved_db)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    return client


def _capture_read_statements(engine, call):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lstrip().lower()
        if normalized.startswith(("select", "with")):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return result, statements


def test_scale_corpus_search_open_and_child_pages_keep_complete_operator_group(
    saved_db, monkeypatch
):
    manifest = seed_scale_corpus(saved_db)
    assert manifest["synthetic_fixture"] is True
    assert manifest["group_count"] == 417
    assert manifest["sector_counts"] == {"oil_gas": 1980, "data_centers": 18, "other": 100}
    target = manifest["groups"]["de_central"]
    client = _client(saved_db, monkeypatch)

    first_header = client.get(
        "/api/opportunities/groups",
        params={"sector": "all", "sort": "company", "limit": 50},
    )
    assert first_header.status_code == 200, first_header.text
    assert first_header.json()["total"] == 417
    assert target["id"] not in {item["id"] for item in first_header.json()["items"]}

    response, read_statements = _capture_read_statements(
        saved_db.kw["bind"],
        lambda: client.get(
            f"/api/opportunities/groups/{target['id']}/open",
            params={
                "sector": "oil_gas",
                "sort": "updated",
                "limit": 25,
            },
        ),
    )
    assert response.status_code == 200, response.text
    # The authenticated route includes one session lookup, generation
    # selection, one combined header/child-anchor read, and bounded project
    # detail serialization. It must not materialize the unused parent page or
    # facets as additional cohort reads. This synthetic fixture has no contact
    # records; real contact-bearing pages retain the separate privacy-ledger
    # read performed by the shared serializer.
    assert len(read_statements) <= 4
    opened = response.json()
    assert opened["generation"] == manifest["generation_id"]
    assert opened["group"]["name"] == target["name"]
    assert opened["group"]["project_count"] == target["project_count"]
    assert opened["group"]["need_count"] == 48
    assert opened["group"]["priority_score"] == 9999
    assert opened["group"]["sectors"] == ["oil_gas"]
    first = opened["projects"]
    assert first["total"] == target["project_count"]
    assert first["limit"] == 25
    assert len(first["items"]) == 25
    assert len(first["items"]) <= first["limit"]
    first_ids = {item["project_id"] for item in first["items"]}
    assert first_ids <= set(target["project_ids"])
    assert target["project_ids"][47] not in first_ids
    assert any(
        need["name"].startswith("STORMCHASER")
        for result in first["items"]
        for need in result["needs"]
    )

    next_response = client.get(
        f"/api/opportunities/groups/{target['id']}/projects",
        params={
            "sector": "oil_gas",
            "sort": "updated",
            "limit": 25,
            "offset": 25,
            "cohort_token": first["cohort_token"],
            "parent_cohort_token": opened["parent_cohort_token"],
        },
    )
    assert next_response.status_code == 200, next_response.text
    second = next_response.json()
    second_ids = {item["project_id"] for item in second["items"]}
    assert second["total"] == first["total"] == 48
    assert len(second["items"]) == 23
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == set(target["project_ids"])

    parent = client.get(
        "/api/opportunities/groups",
        params={"sector": "oil_gas", "sort": "updated", "limit": 1},
    )
    assert parent.status_code == 200, parent.text
    assert opened["parent_cohort_token"] == parent.json()["cohort_token"]

    search_result = client.get(
        "/api/opportunities/groups",
        params={"search": target["search"], "sector": "oil_gas"},
    )
    assert search_result.status_code == 200, search_result.text
    assert search_result.json()["total"] == 1
    assert search_result.json()["items"][0]["project_count"] == 48

    searched_open = client.get(
        f"/api/opportunities/groups/{target['id']}/open",
        params={
            "search": target["search"],
            "sector": "oil_gas",
            "region": "Texas",
            "stage": "permit_issued",
            "priority": "ranked",
            "limit": 25,
        },
    )
    assert searched_open.status_code == 200, searched_open.text
    filtered_page = searched_open.json()["projects"]
    assert filtered_page["total"] == 48
    filtered_next = client.get(
        f"/api/opportunities/groups/{target['id']}/projects",
        params={
            "search": target["search"],
            "sector": "oil_gas",
            "region": "Texas",
            "stage": "permit_issued",
            "priority": "ranked",
            "sort": "priority",
            "limit": 25,
            "offset": 25,
            "cohort_token": filtered_page["cohort_token"],
            "parent_cohort_token": searched_open.json()["parent_cohort_token"],
        },
    )
    assert filtered_next.status_code == 200, filtered_next.text
    filtered_second = filtered_next.json()
    assert filtered_second["total"] == 48
    first_filtered_ids = {item["project_id"] for item in filtered_page["items"]}
    second_filtered_ids = {item["project_id"] for item in filtered_second["items"]}
    assert len(filtered_page["items"]) == 25
    assert len(filtered_second["items"]) == 23
    assert first_filtered_ids.isdisjoint(second_filtered_ids)
    assert first_filtered_ids | second_filtered_ids == set(target["project_ids"])

    detail_need_id = filtered_second["items"][0]["representative_need_id"]
    with saved_db() as session:
        eligible_detail_needs = session.scalar(
            select(func.count())
            .select_from(PowerNeed)
            .join(Project, PowerNeed.project_id == Project.id)
            .where(
                PowerNeed.id.in_([UUID(value) for value in target["need_ids"]]),
                PowerNeed.active.is_(True),
                Project.region_status == "ELIGIBLE",
            )
        )
    assert eligible_detail_needs == 48
    detail = client.get(f"/api/opportunities/needs/{detail_need_id}")
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["id"] == detail_need_id
    assert detail_payload["project_id"] in target["project_ids"]
    assert detail_payload["required_mw"] is None
    assert "Synthetic fixture only" in detail_payload["assessment_reason"]


def test_scale_corpus_global_customer_pagination_and_filter_cohorts(saved_db, monkeypatch):
    manifest = seed_scale_corpus(saved_db)
    client = _client(saved_db, monkeypatch)
    params = {"sector": "oil_gas", "sort": "priority_asc", "limit": 25}

    first_response = client.get("/api/opportunities/groups", params=params)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    assert first["total"] > 50
    assert len(first["items"]) == 25
    second_response = client.get(
        "/api/opportunities/groups",
        params={**params, "offset": 25, "cohort_token": first["cohort_token"]},
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["total"] == first["total"]
    assert len(second["items"]) == 25
    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)

    target = manifest["groups"]["de_central"]
    operator_search = client.get(
        "/api/opportunities/groups",
        params={"search": target["operator_number"], "sector": "oil_gas"},
    )
    assert operator_search.status_code == 200, operator_search.text
    search_result = operator_search.json()
    assert search_result["total"] == 1
    assert search_result["items"][0]["id"] == target["id"]
    assert search_result["items"][0]["project_count"] == 48

    regional = client.get(
        "/api/opportunities/groups",
        params={
            "sector": "oil_gas",
            "search": target["operator_number"],
            "region": "Texas",
            "priority": "ranked",
        },
    )
    assert regional.status_code == 200, regional.text
    regional_target = next(item for item in regional.json()["items"] if item["id"] == target["id"])
    assert regional_target["project_count"] == 48
    assert regional.json()["items"][0]["project_count"] > 0

    stage = client.get(
        "/api/opportunities/groups",
        params={
            "sector": "oil_gas",
            "search": target["operator_number"],
            "stage": "permit_issued",
            "priority": "ranked",
        },
    )
    assert stage.status_code == 200, stage.text
    stage_target = next(item for item in stage.json()["items"] if item["id"] == target["id"])
    assert stage_target["project_count"] == 48

    for unmatched_filter in (
        {"search": "synthetic-no-such-customer", "sector": "oil_gas"},
        {"sector": "oil_gas", "region": "Atlantis"},
        {"sector": "oil_gas", "stage": "synthetic-no-such-stage"},
    ):
        unmatched = client.get("/api/opportunities/groups", params=unmatched_filter)
        assert unmatched.status_code == 200, unmatched.text
        assert unmatched.json()["total"] == 0

    unranked = client.get(
        "/api/opportunities/groups",
        params={"sector": "data_centers", "priority": "unranked"},
    )
    assert unranked.status_code == 200, unranked.text
    assert unranked.json()["items"] == []


def test_scale_corpus_unconfirmed_name_bucket_keeps_distinct_identity_children(
    saved_db, monkeypatch
):
    manifest = seed_scale_corpus(saved_db)
    target = manifest["groups"]["amazon"]
    client = _client(saved_db, monkeypatch)

    opened_response = client.get(
        f"/api/opportunities/groups/{target['id']}/open",
        params={"sector": "data_centers", "limit": 25},
    )
    assert opened_response.status_code == 200, opened_response.text
    opened = opened_response.json()
    assert opened["group"]["group_kind"] == "same_name_unconfirmed"
    assert opened["group"]["identity_count"] == 3
    assert opened["group"]["project_count"] == 3
    children = opened["projects"]
    assert children["total"] == 3
    assert {item["project_id"] for item in children["items"]} == set(target["project_ids"])
    assert {item["customer_identity_id"] for item in children["items"]} == set(
        target["identity_ids"]
    )
    assert len({item["customer_identity_id"] for item in children["items"]}) == 3
