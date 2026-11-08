"""PostgreSQL project-first projection and authenticated route contracts."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    global_method_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
    person_suppression_key,
)
from gridlens.intelligence.project_results import page
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseRow,
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    Evidence,
    NeedObservation,
    PersonIdentity,
    SignalDecision,
)
from gridlens.persistence.suppression_models import ContactSuppression
from gridlens.security import token_for
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


def _seed_project_metadata(factory):
    from test_saved_browse import seed

    seed(factory, count=5, histories=1)
    company_id, person_id = uuid4(), uuid4()
    rebuild(factory)
    with factory.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.need_id)
        ).all()
        assert len(rows) == 5
        # Two needs share a Project, a separate permit Project validates to
        # that same well API, and another API stays distinct under the operator.
        rows[1].project_id = rows[0].project_id
        for index, row in enumerate(rows):
            category = "oil_gas" if index < 4 else "data_centers"
            identity = None
            if index < 3:
                identity = {
                    "kind": "us_well_api",
                    "value": "4216538299",
                    "identity_validated": True,
                }
            elif index == 3:
                identity = {
                    "kind": "us_well_api",
                    "value": "4216538001",
                    "identity_validated": True,
                }
            row.compact = {
                **row.compact,
                "project_metadata": {
                    "sector": category,
                    "title": f"Asset {index}",
                    "operator": "Same Operator",
                    "event": {
                        "kind": "permit_issued",
                        "label": "Permit issued",
                        "date": f"2026-10-{index + 1:02d}",
                    },
                    "power_summary": f"Distinct prepared power context {index}",
                    "asset_identity": identity,
                },
                "contact_actions": [
                    {
                        "kind": "email",
                        "href": "mailto:private@example.invalid",
                        "company": "Same Operator",
                        "name": "Private Person",
                        "company_identity_id": str(company_id),
                        "person_identity_id": str(person_id),
                        "claim_id": f"claim-{index}",
                    }
                ],
                "contact_people": [
                    {
                        "record_type": "contact_person",
                        "company_identity_id": str(company_id),
                        "person_identity_id": str(person_id),
                        "company": "Same Operator",
                        "name": "Private Person",
                        "role": "operations",
                    }
                ],
                "contacts": [{"email": "suppressed@example.invalid"}],
                "commercial_preview": {"next_action": f"Distinct action {index}"},
            }
        return company_id


def test_project_groups_needs_filters_sector_and_fences_pagination(saved_db):
    company_id = _seed_project_metadata(saved_db)
    with saved_db() as session:
        default = page(session, sector="all")
        assert default["total"] == 0 and default["items"] == []
        assert default["results_scope"] == "qualified"
        first = page(session, sector="all", search="Synthetic", limit=1)
        assert first["count_unit"] == "projects"
        assert first["total"] == 3
        full = page(session, sector="all", search="Synthetic", limit=50)
        grouped = next(item for item in full["items"] if item["need_count"] == 3)
        for sort in ("company", "project", "priority_asc"):
            sorted_items = page(session, search="Synthetic", sort=sort)["items"]
            assert {
                i["id"]: (i["project_id"], i["representative_need_id"], i["need_count"])
                for i in sorted_items
            } == {
                i["id"]: (i["project_id"], i["representative_need_id"], i["need_count"])
                for i in full["items"]
            }
        assert grouped["company"] == "Same Operator"
        assert len(grouped["project_ids"]) == 2
        assert grouped["asset_identity"]["value"] == "4216538299"
        assert grouped["id"] not in grouped["project_ids"]
        assert grouped["project_id"] in grouped["project_ids"]
        scoped = page(session, need_id=UUID(grouped["needs"][0]["id"]), limit=1)
        assert scoped["total"] == 1 and scoped["items"][0]["id"] == grouped["id"]
        assert scoped["items"][0]["need_count"] == 3
        assert scoped["results_scope"] == "discovery"
        assert page(session, need_id=uuid4())["items"] == []
        lower_need = grouped["needs"][-1]
        selected = page(session, need_id=UUID(lower_need["id"]), limit=1)["items"][0]
        assert selected["representative_need_id"] == lower_need["id"]
        assert selected["event"] == lower_need["project_metadata"]["event"]
        assert selected["power_summary"] == lower_need["project_metadata"]["power_summary"]
        assert selected["next_action"] == lower_need["commercial_preview"]["next_action"]
        assert grouped["commercial_brief"]["version"]
        assert grouped["needs"][0]["commercial_brief"]["power_need"]["value"] is None
        assert (
            grouped["commercial_brief"]["best_contact"]["href"] == "mailto:private@example.invalid"
        )
        assert "contacts" not in grouped["needs"][0]
        assert "suppressed@example.invalid" not in repr(full["items"])
        second = page(
            session,
            sector="all",
            search="Synthetic",
            limit=1,
            offset=1,
            token=first["cohort_token"],
        )
        assert second["items"][0]["id"] != first["items"][0]["id"]
        oil = page(session, sector="oil_gas")
        dc = page(session, sector="data_centers")
        assert oil["total"] == 2
        assert sorted(item["need_count"] for item in oil["items"]) == [1, 3]
        assert len({item["id"] for item in oil["items"]}) == 2
        assert dc["total"] == 1 and dc["items"][0]["sector"] == "data_centers"
        with pytest.raises(HTTPException) as stale:
            page(session, sector="oil_gas", offset=1, token=first["cohort_token"])
        assert getattr(stale.value, "status_code", None) in {409, 422}
        before_suppression = page(session, sector="oil_gas")
        # Saved actions with synthetic/nonexistent claim IDs cannot outlive the
        # current canonical buying-chain projection after a restart or refresh.
        assert before_suppression["items"][0]["contact"] == []
        assert before_suppression["items"][0]["contact_people"] == []
    # Method suppression added after snapshot creation removes call/email routes
    # while preserving a separately supported named person without a method.
    with saved_db.begin() as writer:
        writer.add(
            ContactSuppression(
                scope="method",
                subject_key=method_suppression_key(
                    company_id, "Private Person", "email", "mailto:private@example.invalid"
                ),
                expected_version=0,
                version=1,
                action="suppress",
                reason="integration method suppression",
                actor="test",
                idempotency_key="issue128-project-results-method",
            )
        )
    with saved_db() as session:
        method_suppressed = page(session, sector="oil_gas")
        assert method_suppressed["items"][0]["contact"] == []
        assert method_suppressed["items"][0]["contact_people"] == []
        assert all(
            not need.get("contact_actions") for need in method_suppressed["items"][0]["needs"]
        )
        assert all(
            not need.get("contact_people") for need in method_suppressed["items"][0]["needs"]
        )
    # Person suppression removes the role record as well; company suppression
    # then covers every company-level route regardless of person or method.
    with saved_db.begin() as writer:
        writer.add(
            ContactSuppression(
                scope="person",
                subject_key=person_suppression_key(company_id, "Private Person"),
                expected_version=0,
                version=1,
                action="suppress",
                reason="integration person suppression",
                actor="test",
                idempotency_key="issue128-project-results-person",
            )
        )
    with saved_db() as session:
        person_suppressed = page(session, sector="oil_gas")
        assert person_suppressed["items"][0]["contact_people"] == []
    with saved_db.begin() as writer:
        writer.add(
            ContactSuppression(
                scope="company",
                subject_key=company_suppression_key(company_id),
                expected_version=0,
                version=1,
                action="suppress",
                reason="integration company suppression",
                actor="test",
                idempotency_key="issue128-project-results-company",
            )
        )
    with saved_db() as session:
        company_suppressed = page(session, sector="oil_gas")
        assert company_suppressed["items"][0]["contact"] == []
        assert company_suppressed["items"][0]["contact_people"] == []
        assert company_suppressed["items"][0]["commercial_brief"]["best_contact"] is None


def test_source_bound_shortlist_filters_before_counts_and_keeps_all_projects_unchanged(saved_db):
    from test_saved_browse import seed

    need_ids = seed(saved_db, count=3, histories=1)
    with saved_db.begin() as session:
        abstracts = {
            need_ids[0]: (
                "Project: North Campus\nScope: A new data center campus is under construction "
                "and commissioning is planned. Jane Doe can be reached at +44 20 7946 0958 "
                "or +49 30 901820."
            ),
            need_ids[
                1
            ]: "Project: Permit site\nScope: TEMPORARY ELECTRICAL PERMIT for fence and drainage.",
            need_ids[
                2
            ]: "Project: Old campus\nStatus: Complete\nScope: Data center construction finished.",
        }
        linked = session.execute(
            select(NeedObservation.need_id, Evidence).join(
                Evidence, Evidence.observation_id == NeedObservation.observation_id
            )
        ).all()
        for need_id, evidence in linked:
            if need_id in abstracts:
                evidence.title = f"Project update {need_id}"
                evidence.abstract = abstracts[need_id]
    rebuild(saved_db)
    with saved_db.begin() as session:
        browse_rows = session.scalars(select(BrowseRow)).all()
        evidence_by_observation = {
            evidence.observation_id: evidence
            for evidence in session.scalars(select(Evidence)).all()
        }
        for row in browse_rows:
            evidence = next(
                evidence
                for evidence in evidence_by_observation.values()
                if session.scalar(
                    select(NeedObservation.need_id).where(
                        NeedObservation.observation_id == evidence.observation_id,
                        NeedObservation.need_id == row.need_id,
                    )
                )
            )
            row.summary = {
                **(row.summary or {}),
                "evidence": [
                    {
                        "id": str(evidence.id),
                        "source_id": "synthetic-permits",
                        "assessment_current": True,
                    }
                ],
            }
        selected = next(row for row in browse_rows if row.need_id == need_ids[0])
        person = PersonIdentity()
        session.add(person)
        session.flush()
        now = datetime.now(UTC)
        claim = BuyingChainClaim(
            project_id=selected.project_id,
            entity_key="shortlist-subject-jane-doe",
            fingerprint="d" * 64,
            policy_version="shortlist-privacy-test",
            organization="Synthetic campus owner",
            person_name="Jane Doe",
            title="Project contact",
            category="owner",
            organization_relationship="owner",
            person_organization_relationship="employee",
            person_project_relationship="project_contact",
            evidence_strength="high",
            reason="Synthetic privacy regression fixture",
            citations=[],
            public_contacts=[],
            observed_at=now,
        )
        session.add(claim)
        session.flush()
        identity_evidence = BuyingChainEvidence(
            project_id=selected.project_id,
            url="https://example.test/shortlist-identity",
            title="Synthetic identity source",
            excerpt="Jane Doe is associated with this synthetic project.",
            content_hash="e" * 64,
            extraction_location="fixture",
            observed_at=now,
            last_seen_at=now,
            project_match_reason="Synthetic shortlist privacy fixture",
        )
        session.add(identity_evidence)
        session.flush()
        session.add_all(
            [
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type="person",
                    person_identity_id=person.id,
                    reason="Synthetic identity fixture",
                    basis="strong_identifier",
                    source_evidence_id=identity_evidence.id,
                    source_version_hash="f" * 64,
                    state="current",
                ),
                ContactSuppression(
                    scope="person",
                    subject_key=global_person_suppression_key(person.id),
                    expected_version=0,
                    version=1,
                    action="suppress",
                    reason="Synthetic shortlist privacy regression",
                    actor="test",
                    idempotency_key="shortlist-person-privacy",
                ),
                ContactSuppression(
                    scope="method",
                    subject_key=global_method_suppression_key("phone", "+44 20 7946 0958"),
                    expected_version=0,
                    version=1,
                    action="suppress",
                    reason="Synthetic shortlist privacy regression",
                    actor="test",
                    idempotency_key="shortlist-phone-privacy",
                ),
            ]
        )
    # The retained-claim insertion invalidates the derived browse generation;
    # rebuild after it, then restore its bounded source refs for this fixture.
    rebuild(saved_db)
    with saved_db.begin() as session:
        browse_rows = session.scalars(select(BrowseRow)).all()
        evidence_by_observation = {
            evidence.observation_id: evidence
            for evidence in session.scalars(select(Evidence)).all()
        }
        for row in browse_rows:
            evidence = next(
                evidence
                for evidence in evidence_by_observation.values()
                if session.scalar(
                    select(NeedObservation.need_id).where(
                        NeedObservation.observation_id == evidence.observation_id,
                        NeedObservation.need_id == row.need_id,
                    )
                )
            )
            row.summary = {
                **(row.summary or {}),
                "evidence": [
                    {
                        "id": str(evidence.id),
                        "source_id": "synthetic-permits",
                        "assessment_current": True,
                    }
                ],
            }
    with saved_db() as session:
        generation = current_generation(session)
        shortlist = page(session, shortlist=True, limit=1, selected_generation=generation)
        assert shortlist["total"] == 1
        assert len(shortlist["items"]) == 1
        assessment = shortlist["items"][0]["shortlist_assessment"]
        assert assessment["eligible"] is True
        assert assessment["evidence_refs"]
        assert "under construction" in assessment["why_now"].lower()
        assert "Jane Doe" not in repr(assessment)
        assert "+44 20 7946 0958" not in repr(assessment)
        assert "+49 30 901820" not in repr(assessment)
        brief_text = repr(shortlist["items"][0]["commercial_brief"])
        assert "Jane Doe" not in brief_text
        assert "+44 20 7946 0958" not in brief_text
        assert "+49 30 901820" not in brief_text
        detail = page(session, shortlist=True, need_id=need_ids[0])
        assert detail["total"] == 1
        assert (
            detail["items"][0]["shortlist_assessment"]["evidence_refs"]
            == assessment["evidence_refs"]
        )
        all_projects = page(session, shortlist=False, include_signals=True)
        assert all_projects["total"] == 3
        assert all("shortlist_assessment" not in item for item in all_projects["items"])
        assert shortlist["cohort_token"] != all_projects["cohort_token"]

        # A current, pinned demand decision can veto only its exact retained
        # source version. Non-Jev/legacy decisions abstain.
        evidence = session.scalar(
            select(Evidence).where(Evidence.id == UUID(assessment["evidence_refs"][0]))
        )
        decision = SignalDecision(
            observation_id=evidence.observation_id,
            content_hash=evidence.content_hash,
            policy_version="signal-display-v2",
            decision="HOLD",
            source="jev",
            model_version=settings.jev_model,
            dimensions={"question_set": "demand-v1"},
            reason="Synthetic source-bound display test",
        )
        session.add(decision)
        session.flush()
        with pytest.raises(HTTPException) as stale_cohort:
            page(
                session,
                shortlist=True,
                limit=1,
                offset=1,
                token=shortlist["cohort_token"],
                selected_generation=generation,
            )
        assert stale_cohort.value.status_code == 409
        assert page(session, shortlist=True, limit=1, selected_generation=generation)["total"] == 0

        decision.source = "deterministic"
        session.flush()
        assert page(session, shortlist=True, limit=1, selected_generation=generation)["total"] == 1
        decision.source = "jev"
        session.flush()
        legacy_decision = SignalDecision(
            observation_id=evidence.observation_id,
            content_hash=evidence.content_hash,
            policy_version="signal-display-v2",
            decision="SHOW",
            source="jev",
            model_version=settings.jev_model,
            dimensions={"question_set": "temporary-power-v2"},
            reason="Later legacy question set must not replace demand-v1 hold",
        )
        session.add(legacy_decision)
        session.flush()
        assert page(session, shortlist=True, limit=1, selected_generation=generation)["total"] == 0
        later_review = SignalDecision(
            observation_id=evidence.observation_id,
            content_hash=evidence.content_hash,
            policy_version="signal-display-v2",
            decision="REVIEW",
            source="jev",
            model_version=settings.jev_model,
            dimensions={"question_set": "demand-v1"},
            reason="Later review supersedes the earlier hold",
        )
        session.add(later_review)
        session.flush()
        assert page(session, shortlist=True, limit=1, selected_generation=generation)["total"] == 1


def test_project_results_route_requires_session(saved_db, monkeypatch):
    _seed_project_metadata(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    import gridlens.api.app as api

    monkeypatch.setattr(api, "SessionLocal", saved_db)
    with TestClient(api.app, base_url="https://testserver") as client:
        response = client.get("/api/opportunities/projects")
        assert response.status_code == 401
        client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
        response = client.get("/api/opportunities/projects")
        assert response.status_code == 200, response.text
        assert response.json()["count_unit"] == "projects"
        assert response.json()["results_scope"] == "qualified"
        assert response.json()["total"] == 0
        discovery = client.get("/api/opportunities/projects?include_signals=true&limit=1")
        assert discovery.status_code == 200, discovery.text
        discovery_page = discovery.json()
        assert discovery_page["results_scope"] == "discovery"
        assert discovery_page["total"] > 0
        assert discovery_page["items"]
        with saved_db() as session:
            generation = current_generation(session)
            assert discovery_page["generation_id"] == str(generation.id)
            assert discovery_page["as_of"] == generation.built_at.isoformat()
            assert discovery_page["valid_until"] == generation.valid_until.isoformat()
            assert datetime.fromisoformat(discovery_page["valid_until"]) > datetime.now(UTC)
            assert discovery_page["qualification_state"] == "current"
            assert discovery_page["refresh_state"] == "current"
        exact_need_id = discovery_page["items"][0]["needs"][0]["id"]
        exact_need = client.get(f"/api/opportunities/needs/{exact_need_id}")
        assert exact_need.status_code == 200, exact_need.text
        shortlist_response = client.get(
            "/api/opportunities/projects", params={"shortlist": "true", "limit": 1}
        )
        assert shortlist_response.status_code == 200, shortlist_response.text
        assert shortlist_response.json()["total"] == 0
        assert shortlist_response.json()["cohort_token"] != discovery_page["cohort_token"]
        for sort in ("priority", "priority_asc", "company", "project", "updated"):
            sorted_response = client.get(
                "/api/opportunities/projects",
                params={
                    "include_signals": "true",
                    "sort": sort,
                    "limit": 1,
                },
            )
            assert sorted_response.status_code == 200, sorted_response.text
        assert client.get("/api/opportunities/projects?sort=invalid").status_code == 422
        assert any(need["tier"] == "Signal" for need in discovery_page["items"][0]["needs"])
        mismatched_cohort = client.get(
            "/api/opportunities/projects",
            params={
                "include_signals": "false",
                "limit": 1,
                "cohort_token": discovery_page["cohort_token"],
            },
        )
        assert mismatched_cohort.status_code == 409
        invalid = client.get("/api/opportunities/projects?include_signals=perhaps")
        assert invalid.status_code == 422


def test_customer_rollup_context_is_bound_to_parent_and_child_tokens():
    from gridlens.intelligence.customer_results import _cohort

    class Generation:
        id = uuid4()
        digest = "stable"

    generation = Generation()
    base = _cohort(
        None, search="operator", sector="oil_gas", sort="priority", selected_generation=generation
    )[2]
    assert (
        base
        != _cohort(
            None,
            search="operator",
            sector="oil_gas",
            sort="company",
            selected_generation=generation,
        )[2]
    )
    assert (
        base
        != _cohort(
            None,
            search="operator",
            sector="oil_gas",
            sort="priority",
            region="Texas",
            selected_generation=generation,
        )[2]
    )
    assert (
        base
        != _cohort(
            None,
            search="operator",
            sector="oil_gas",
            sort="priority",
            stage="permit_issued",
            selected_generation=generation,
        )[2]
    )
    assert (
        base
        != _cohort(
            None,
            search="operator",
            sector="oil_gas",
            sort="priority",
            priority="ranked",
            selected_generation=generation,
        )[2]
    )


@pytest.mark.parametrize(
    "sort,field",
    [
        ("company", "company"),
        ("project", "name"),
        ("priority_asc", "priority_score"),
    ],
)
def test_project_sort_orders_entire_cohort_before_pagination(saved_db, sort, field):
    from test_saved_browse import seed

    seed(saved_db, count=6, histories=1)
    rebuild(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.need_id)
        ).all()
        for index, row in enumerate(rows):
            row.rank_score = 100 - index
            row.compact = {
                **row.compact,
                "project_metadata": {
                    "title": ["Zulu", "Beta", "alpha", "ALPHA", "Delta", "Echo"][index],
                    "operator": ["Zulu", None, "alpha", "ALPHA", "Delta", "Echo"][index],
                },
            }
            if index == 5:
                row.compact = {
                    **row.compact,
                    "name": None,
                    "browse_title": None,
                    "project_metadata": {"operator": "Echo"},
                }
    with saved_db() as session:
        full = page(session, include_signals=True, sort=sort)
        values = [item[field] for item in full["items"]]
        expected = sorted(
            values, key=lambda v: (v is None, v.casefold() if isinstance(v, str) else v)
        )
        assert values == expected
        seen = []
        token = full["cohort_token"]
        for offset in range(0, 6, 2):
            result = page(
                session, include_signals=True, sort=sort, limit=2, offset=offset, token=token
            )
            seen.extend(item["id"] for item in result["items"])
        assert seen == [item["id"] for item in full["items"]]
        assert len(set(seen)) == 6
        assert seen == [
            item["id"] for item in page(session, include_signals=True, sort=sort)["items"]
        ]
        if sort in {"company", "project"}:
            tied = [
                item["id"]
                for item in full["items"]
                if isinstance(item[field], str) and item[field].casefold() == "alpha"
            ]
            assert tied == sorted(tied)
        baseline = page(session, include_signals=True)
        assert {i["id"]: i["representative_need_id"] for i in full["items"]} == {
            i["id"]: i["representative_need_id"] for i in baseline["items"]
        }
        with pytest.raises(HTTPException) as mismatch:
            page(session, include_signals=True, sort="updated", limit=2, offset=2, token=token)
        assert mismatch.value.status_code == 409


@pytest.mark.parametrize(
    "first_title,expected_first",
    [
        ("Zulu · Alpha Asset", "Zulu · Alpha Asset"),
        ("zulu · Alpha Asset", "Alpha · Beta Asset"),
    ],
)
def test_project_sort_uses_visible_name_without_exact_company_prefix(
    saved_db, first_title, expected_first
):
    from test_saved_browse import seed

    seed(saved_db, count=2, histories=1)
    rebuild(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.need_id)
        ).all()
        for row, company, title in zip(
            rows, ("Zulu", "Alpha"), (first_title, "Alpha · Beta Asset"), strict=True
        ):
            row.compact = {
                **row.compact,
                "project_metadata": {
                    "title": title,
                    "operator": company,
                },
            }
    with saved_db() as session:
        first = page(session, include_signals=True, sort="project", limit=1)
        assert first["items"][0]["name"] == expected_first
        second = page(
            session,
            include_signals=True,
            sort="project",
            limit=1,
            offset=1,
            token=first["cohort_token"],
        )
        assert {first["items"][0]["name"], second["items"][0]["name"]} == {
            first_title,
            "Alpha · Beta Asset",
        }
