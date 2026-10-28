"""Authenticated HTTP contract for the grouped opportunity endpoints."""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import BrowseRow, BrowseState
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
    assert client.get("/api/opportunities/groups/example/open").status_code == 401
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

    filtered_missing = client.get(
        f"/api/opportunities/groups/{group_id}/open", params={"search": "definitely-absent"}
    )
    assert filtered_missing.status_code == 404
    absent = client.get("/api/opportunities/groups/cg_00000000000000000000000000000000/open")
    assert absent.status_code == 404

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
    assert (
        client.get(f"/api/opportunities/groups/{group_id}/open", params={"limit": 0}).status_code
        == 422
    )
    assert (
        client.get(f"/api/opportunities/groups/{group_id}/open", params={"limit": 51}).status_code
        == 422
    )


def test_customer_group_open_resolves_group_after_first_header_page(saved_db, monkeypatch):
    from test_saved_browse import seed

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")
    from gridlens.persistence.models import BrowseCustomerMembership, CompanyIdentity

    with saved_db.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow).where(BrowseRow.generation_id == generation.id)
        ).all()
        identities = [CompanyIdentity() for _ in rows]
        session.add_all(identities)
        session.flush()
        for index, row in enumerate(rows):
            row.compact = {**row.compact, "tier": "Prospect"}
            row.compact = {
                **row.compact,
                "project_metadata": {"sector": "oil_gas", "title": f"Operator {index:03d}"},
            }
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=identities[index].id,
                    project_id=row.project_id,
                    organization_name=f"Operator {index:03d}",
                    role="customer",
                )
            )
    from gridlens.intelligence.saved_browse import rebuild as rebuild_again

    assert rebuild_again(saved_db)["status"] == "published"
    with saved_db() as session:
        from gridlens.intelligence.customer_results import groups

        parent = groups(session, sector="all", limit=50, sort="updated")
        assert parent["total"] == len(rows)
        target_id = parent["items"][-1]["id"]
        assert target_id not in {
            item["id"] for item in groups(session, sector="all", limit=1, sort="updated")["items"]
        }

    monkeypatch.setattr(api, "SessionLocal", saved_db)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(
        f"/api/opportunities/groups/{target_id}/open", params={"sector": "all", "sort": "updated"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["group"]["id"] == target_id
    with saved_db() as session:
        assert target_id not in {
            item["id"] for item in groups(session, sector="all", limit=1, sort="updated")["items"]
        }


def test_customer_group_open_uses_one_generation_across_all_serializers(saved_db, monkeypatch):
    from test_saved_browse import seed

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")

    with saved_db.begin() as session:
        old_generation_id = current_generation(session).id
        state = session.get(BrowseState, 1)
        state.prepared_generation_id = uuid4()
        new_generation_id = state.prepared_generation_id
        from gridlens.persistence.models import BrowseGeneration

        old_generation = session.get(BrowseGeneration, old_generation_id)
        new_generation = type(old_generation)(
            id=new_generation_id,
            input_revision=old_generation.input_revision,
            policy_version=old_generation.policy_version,
            built_at=old_generation.built_at,
            valid_from=old_generation.valid_from + timedelta(seconds=1),
            valid_until=old_generation.valid_until,
            row_count=old_generation.row_count,
            digest=old_generation.digest,
            counts=old_generation.counts,
        )
        session.add(new_generation)
        session.flush()

    monkeypatch.setattr(api, "SessionLocal", saved_db)
    generation_reads = []
    from gridlens.intelligence import saved_browse

    original_current_generation = saved_browse.current_generation

    def counted_generation(session, **kwargs):
        generation_reads.append(True)
        return original_current_generation(session, **kwargs)

    session_token = token_for(int(datetime.now(UTC).timestamp()) + 300)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", session_token)
    response = client.get("/api/opportunities/groups", params={"search": "Synthetic", "limit": 1})
    group_id = response.json()["items"][0]["id"]

    # The route selection returns A once; subsequent selectors would return B.
    route_selection_count = 0

    def select_a_then_b(session, **kwargs):
        nonlocal route_selection_count
        route_selection_count += 1
        if route_selection_count == 1:
            return old_generation
        return new_generation

    monkeypatch.setattr(api, "current_generation", select_a_then_b)
    from gridlens.intelligence import customer_results

    monkeypatch.setattr(customer_results, "current_generation", counted_generation)
    from gridlens.intelligence import project_results

    monkeypatch.setattr(project_results, "current_generation", counted_generation)
    opened = client.get(
        f"/api/opportunities/groups/{group_id}/open", params={"search": "Synthetic"}
    )
    assert opened.status_code == 200, opened.text
    payload = opened.json()
    assert payload["generation"] == str(old_generation.id)
    assert payload["projects"]["generation"] == str(old_generation.id)
    assert payload["group"]["id"] == group_id
    assert route_selection_count == 1
    assert len(generation_reads) == 0

    transaction_settings = {}

    def capture_read_only(session, **kwargs):
        transaction_settings["isolation"] = session.execute(
            text("SELECT current_setting('transaction_isolation')")
        ).scalar_one()
        transaction_settings["read_only"] = session.execute(
            text("SELECT current_setting('transaction_read_only')")
        ).scalar_one()
        return original_current_generation(session, **kwargs)

    monkeypatch.setattr(api, "current_generation", capture_read_only)
    readonly_response = client.get(
        f"/api/opportunities/groups/{group_id}/open", params={"search": "Synthetic"}
    )
    assert readonly_response.status_code == 200
    assert transaction_settings == {"isolation": "repeatable read", "read_only": "on"}


def test_customer_group_open_rechecks_current_contact_suppressions(saved_db, monkeypatch):
    from test_saved_browse import seed

    seed(saved_db, count=1, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")
    from gridlens.intelligence.contact_suppressions import global_method_suppression_key
    from gridlens.persistence.suppression_models import ContactSuppression

    with saved_db.begin() as session:
        generation = current_generation(session)
        row = session.scalar(select(BrowseRow).where(BrowseRow.generation_id == generation.id))
        company_id, person_id = uuid4(), uuid4()
        row.compact = {
            **row.compact,
            "contact_actions": [
                {
                    "kind": "email",
                    "href": "mailto:private@example.test",
                    "company_identity_id": str(company_id),
                    "person_identity_id": str(person_id),
                    "claim_id": "private-claim",
                }
            ],
        }
    from gridlens.intelligence.saved_browse import rebuild as rebuild_again

    assert rebuild_again(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        session.add(
            ContactSuppression(
                scope="method",
                subject_key=global_method_suppression_key("email", "mailto:private@example.test"),
                expected_version=0,
                version=1,
                action="suppress",
                reason="test suppression",
                actor="test",
                idempotency_key="cohort-open-suppression",
            )
        )

    monkeypatch.setattr(api, "SessionLocal", saved_db)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    parent = client.get("/api/opportunities/groups", params={"search": "Synthetic", "limit": 1})
    group_id = parent.json()["items"][0]["id"]
    opened = client.get(
        f"/api/opportunities/groups/{group_id}/open", params={"search": "Synthetic"}
    )
    assert opened.status_code == 200, opened.text
    assert "private@example.test" not in opened.text
    assert "private-claim" not in opened.text


def test_customer_group_open_succeeds_if_generation_publishes_after_parent_read(
    saved_db, monkeypatch
):
    from test_saved_browse import seed

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", saved_db)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    parent = client.get("/api/opportunities/groups", params={"search": "Synthetic", "limit": 1})
    group_id = parent.json()["items"][0]["id"]
    parent_token = parent.json()["cohort_token"]

    from gridlens.intelligence import saved_browse

    original_current = saved_browse.current_generation
    original_rebuild = saved_browse.rebuild
    selected_generation_ids = {}
    did_publish = False

    def publish_between_reads(session, **kwargs):
        nonlocal did_publish
        selected = original_current(session, **kwargs)
        selected_generation_ids["old"] = selected.id
        if not did_publish:
            did_publish = True
            assert original_rebuild(saved_db)["status"] == "published"
        return selected

    monkeypatch.setattr(api, "current_generation", publish_between_reads)
    opened = client.get(
        f"/api/opportunities/groups/{group_id}/open", params={"search": "Synthetic"}
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["generation"] == str(selected_generation_ids["old"])

    assert rebuild(saved_db)["status"] == "published"

    legacy = client.get(
        f"/api/opportunities/groups/{group_id}/projects",
        params={"search": "Synthetic", "parent_cohort_token": parent_token},
    )
    assert legacy.status_code == 409
