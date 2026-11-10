"""Change snapshots retain private history and publish only current, cited roles."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib import import_module
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
    person_suppression_key,
    record_contact_suppression,
)
from gridlens.intelligence.saved_browse import rebuild
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainCorrection,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    ChangeEvent,
    CompanyIdentity,
    PersonIdentity,
)
from gridlens.security import token_for
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]

NOW = datetime(2026, 10, 2, tzinfo=UTC)
ROLE_FIELDS = (
    "organization",
    "person_name",
    "title",
    "category",
    "organization_relationship",
    "person_project_relationship",
)


def _tdlr_case_with_contact():
    from test_buying_chain import TDLR_CASES

    number, name, location, owner, excerpt = TDLR_CASES[1]
    excerpt += (
        "\nOwner contact: Jordan Smith"
        "\nOwner contact phone: not stated"
        "\nOwner contact email: jordan.smith@example.test"
    )
    return number, name, location, owner, excerpt


def _candidate_row(candidate):
    return {key: candidate.get(key) for key in ROLE_FIELDS}


@pytest.mark.parametrize(
    "control_scope",
    ("old_company", "old_scoped_person", "corrected_name", "global_person", "method"),
)
@pytest.mark.parametrize("historical_current_identity", ("same", "old"))
def test_change_event_publication_is_current_source_bound_and_read_only(
    saved_db, monkeypatch, control_scope, historical_current_identity
):
    from test_buying_chain import _seed_tdlr_retained_project

    with saved_db.begin() as session:
        project, retained, _owner = _seed_tdlr_retained_project(session, _tdlr_case_with_contact())
        project.region_status = "ELIGIBLE"
        project_id = project.id
        observation_id = retained.observation_id
        enrich_buying_chain(session, project.id, retained_only=True, now=NOW)
        public = buying_chain_view(session, project.id, now=NOW)
        person = next(
            candidate
            for candidate in public["candidates"]
            if candidate.get("person_name") == "Jordan Smith"
        )
        assert person["public_contacts"]
        assert person["company_identity_id"]
        company_id = UUID(str(person["company_identity_id"]))
        event = session.scalar(
            select(ChangeEvent)
            .where(ChangeEvent.project_id == project.id, ChangeEvent.field_name == "buyer")
            .order_by(ChangeEvent.id.desc())
        )
        assert event is not None
        assert any(
            row.get("person_name") == "Jordan Smith"
            for row in (event.new_state or {}).get("value", [])
        )
        event_id = event.id
        event_snapshot = (deepcopy(event.prior_state), deepcopy(event.new_state), event.replay_key)

        # A later exact-name/exact-role snapshot without its own current source
        # cannot borrow the current row's evidence to authenticate either side.
        current_source_id = UUID(
            str(
                next(
                    citation["id"]
                    for citation in person["evidence"]
                    if citation.get("supports") == "organization_person_role"
                    and citation.get("current_support")
                )
            )
        )
        current_source = session.get(BuyingChainEvidence, current_source_id)
        assert current_source is not None
        person_id = person.get("person_identity_id")
        assert person_id is not None
        current_company_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == person["id"],
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        current_person_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == person["id"],
                BuyingChainIdentityLink.entity_type == "person",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert current_company_link is not None and current_person_link is not None
        assert current_company_link.company_identity_id == company_id
        assert current_person_link.person_identity_id == UUID(str(person_id))
        old_company = CompanyIdentity()
        old_person = PersonIdentity()
        session.add_all([old_company, old_person])
        session.flush()
        old_company_id = old_company.id
        old_person_id = old_person.id
        assert old_company_id != company_id
        assert old_person_id != UUID(str(person_id))
        current_claim = session.get(BuyingChainClaim, person["id"])
        assert current_claim is not None
        prior_claim = BuyingChainClaim(
            project_id=project.id,
            entity_key=current_claim.entity_key,
            fingerprint=sha256(b"historical-corrected-name-claim").hexdigest(),
            policy_version=current_claim.policy_version,
            organization=current_claim.organization,
            person_name="Jordan Prior Smith",
            title=current_claim.title,
            category=current_claim.category,
            organization_relationship=current_claim.organization_relationship,
            person_organization_relationship=current_claim.person_organization_relationship,
            person_project_relationship=current_claim.person_project_relationship,
            evidence_strength=current_claim.evidence_strength,
            reason="Historical source-bound name snapshot.",
            citations=deepcopy(current_claim.citations),
            public_contacts=[],
            observed_at=NOW,
        )
        session.add(prior_claim)
        session.flush()
        session.add(
            BuyingChainCorrection(
                project_id=project.id,
                claim_id=prior_claim.id,
                expected_version=prior_claim.fingerprint,
                idempotency_key="historical-corrected-person-name",
                action="amend",
                values={"person_name": "Jordan Corrected Smith"},
                source_evidence_id=None,
                source_version_hash=None,
                reason="Historical corrected name for suppression-scope regression.",
                actor="test",
            )
        )
        session.add_all(
            [
                BuyingChainIdentityLink(
                    claim_id=prior_claim.id,
                    entity_type="company",
                    company_identity_id=(
                        company_id if historical_current_identity == "same" else old_company_id
                    ),
                    reason="Older claim retains the same current canonical identity",
                    basis="reviewed",
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    state="current",
                ),
                BuyingChainIdentityLink(
                    claim_id=prior_claim.id,
                    entity_type="person",
                    person_identity_id=(
                        UUID(str(person_id))
                        if historical_current_identity == "same"
                        else old_person_id
                    ),
                    reason="Older claim retains the same current canonical identity",
                    basis="reviewed",
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    state="current",
                ),
                BuyingChainIdentityLink(
                    claim_id=person["id"],
                    entity_type="company",
                    company_identity_id=old_company_id,
                    person_identity_id=None,
                    reason="Historical alias fixture",
                    basis="reviewed",
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    state="superseded",
                    superseded_at=NOW,
                ),
                BuyingChainIdentityLink(
                    claim_id=person["id"],
                    entity_type="person",
                    company_identity_id=None,
                    person_identity_id=old_person_id,
                    reason="Historical alias fixture",
                    basis="reviewed",
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    state="superseded",
                    superseded_at=NOW,
                ),
                BuyingChainIdentityLink(
                    claim_id=prior_claim.id,
                    entity_type="company",
                    company_identity_id=old_company_id,
                    person_identity_id=None,
                    reason="Historical alias fixture",
                    basis="reviewed",
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    state="superseded",
                    superseded_at=NOW,
                ),
                BuyingChainIdentityLink(
                    claim_id=prior_claim.id,
                    entity_type="person",
                    company_identity_id=None,
                    person_identity_id=old_person_id,
                    reason="Historical alias fixture",
                    basis="reviewed",
                    source_evidence_id=current_source.id,
                    source_version_hash=current_source.content_hash,
                    state="superseded",
                    superseded_at=NOW,
                ),
            ]
        )
        stale_source = BuyingChainEvidence(
            project_id=project.id,
            url=current_source.url,
            title="Jordan Smith private roster snapshot",
            excerpt=current_source.excerpt,
            content_hash=sha256(b"older different source version").hexdigest(),
            extraction_location=current_source.extraction_location,
            observed_at=NOW - timedelta(days=365),
            last_seen_at=NOW - timedelta(days=365),
            published_at=current_source.published_at,
            project_match_reason=current_source.project_match_reason,
        )
        session.add(stale_source)
        session.flush()
        row = _candidate_row(person)
        session.add(
            ChangeEvent(
                observation_id=observation_id,
                content_hash=retained.content_hash,
                kind="buyer_changed",
                project_id=project.id,
                buying_chain_evidence_id=stale_source.id,
                field_name="buyer",
                prior_state={"value": [row]},
                new_state={
                    "value": [row],
                    "buying_chain_evidence_ids": [str(stale_source.id)],
                    "_validated_event_claim_ids": [str(person["id"])],
                },
                material=True,
                source_date=retained.event_date,
                replay_key=sha256(b"unbound-stale-change-event").hexdigest(),
            )
        )
        wrong_company = {**row, "organization": "Lookalike Customer LLC"}
        session.add(
            ChangeEvent(
                observation_id=observation_id,
                content_hash=retained.content_hash,
                kind="buyer_changed",
                project_id=project.id,
                buying_chain_evidence_id=current_source.id,
                field_name="buyer",
                prior_state={"value": [row]},
                new_state={
                    "value": [wrong_company],
                    "buying_chain_evidence_ids": [str(current_source.id)],
                },
                material=True,
                source_date=retained.event_date,
                replay_key=sha256(b"wrong-company-change-event").hexdigest(),
            )
        )

    assert rebuild(saved_db)["status"] == "published"
    from gridlens.intelligence import buying_chain

    public_views = buying_chain.buying_chain_views

    def views_at_fixture_clock(session, project_ids, **kwargs):
        kwargs["now"] = NOW
        return public_views(session, project_ids, **kwargs)

    monkeypatch.setattr(buying_chain, "buying_chain_views", views_at_fixture_clock)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))

    def read_surfaces(*, require_positive=False):
        project_response = client.get(f"/api/projects/{project_id}/changes")
        workspace_response = client.get("/api/opportunities/workspace/changes")
        assert project_response.status_code == 200, project_response.text
        assert workspace_response.status_code == 200, workspace_response.text
        metadata_response = client.get("/api/changes")
        assert metadata_response.status_code == 200, metadata_response.text
        assert "Jordan Smith private roster snapshot" not in metadata_response.text
        assert "jordan.smith@example.test" not in metadata_response.text
        project_events = project_response.json()
        workspace_payload = workspace_response.json()
        workspace_events = workspace_payload["items"]
        assert all("id" not in source for item in workspace_events for source in item["sources"])
        if require_positive:
            valid_project_event = next(
                (
                    item
                    for item in project_events
                    if item["buying_chain_evidence_id"]
                    and item["field"] == "buyer"
                    and any(
                        row.get("person_name") == "Jordan Smith"
                        for row in (item.get("new") or {}).get("value", [])
                    )
                ),
                None,
            )
            assert valid_project_event is not None, project_events
            valid_workspace_event = next(
                item for item in workspace_events if item["event_key"] == f"change:{event_id}"
            )
        else:
            valid_project_event = valid_workspace_event = None
        return project_events, workspace_payload, valid_project_event, valid_workspace_event

    first_project, first_workspace, valid_project, valid_workspace = read_surfaces(
        require_positive=True
    )
    stale_event_item = next(
        item
        for item in first_project
        if str(stale_source.id) in (item.get("new") or {}).get("buying_chain_evidence_ids", [])
    )
    assert stale_event_item["new"]["value"] == []
    assert "Jordan Smith" not in str(stale_event_item)
    buyer_event_keys = {
        item["event_key"]
        for item in first_workspace["items"]
        if item.get("event_key") and item.get("title", "").startswith("Buyer")
    }
    assert valid_project["prior"]["value"] == []
    assert "jordan.smith@example.test" not in str(valid_project)
    assert any("tdlr.texas.gov" in source["url"] for source in valid_project["sources"])
    assert valid_workspace["before_state"]["value"] == []
    assert any(
        row.get("person_name") == "Jordan Smith" for row in valid_workspace["after_state"]["value"]
    )
    assert "Jordan Smith private roster snapshot" not in str(first_project)
    assert "Jordan Smith private roster snapshot" not in str(first_workspace)
    assert "jordan.smith@example.test" not in str(first_workspace)

    # Suppression across historical aliases removes the actor, while the source
    # remains only as original, same-project public organization provenance.
    with saved_db.begin() as session:
        if control_scope == "old_company":
            suppression_scope = "company"
            subject_key = company_suppression_key(old_company_id)
        elif control_scope == "old_scoped_person":
            suppression_scope = "person"
            subject_key = person_suppression_key(old_company_id, "Jordan Smith")
        elif control_scope == "corrected_name":
            suppression_scope = "person"
            subject_key = person_suppression_key(old_company_id, "Jordan Corrected Smith")
        elif control_scope == "global_person":
            suppression_scope = "person"
            subject_key = global_person_suppression_key(old_person_id)
        else:
            # A genuinely visible provenance URL is governed by the historical
            # company plus corrected-name method scope, not today's unnamed scope.
            assert current_source.url in str(first_project)
            assert current_source.url in str(first_workspace)
            suppression_scope = "method"
            subject_key = method_suppression_key(
                old_company_id, "Jordan Corrected Smith", "profile", current_source.url
            )
        record_contact_suppression(
            session,
            scope=suppression_scope,
            subject_key=subject_key,
            action="suppress",
            expected_version=0,
            reason="change-event privacy regression",
            actor="test",
            idempotency_key="change-event-jordan-suppression",
        )
    with saved_db() as session:
        event = session.get(ChangeEvent, event_id)
        assert event is not None
        assert (event.prior_state, event.new_state, event.replay_key) == event_snapshot

    second_project, second_workspace, _, _ = read_surfaces()
    if control_scope == "method":
        # Revoking this provenance URL also removes the native person's only
        # current role proof. The separately supported organization survives.
        assert person["organization"] in str(second_project)
        assert person["organization"] in str(second_workspace)
        assert current_source.url not in str(second_project)
        assert current_source.url not in str(second_workspace)
    else:
        assert "Jordan Smith" not in str(second_project)
        assert "Jordan Smith" not in str(second_workspace)
    assert "jordan.smith@example.test" not in str(second_project)
    assert "jordan.smith@example.test" not in str(second_workspace)
    if control_scope != "method":
        assert all("Jordan Smith" not in str(item.get("new")) for item in second_project)
        assert all(
            "Jordan Smith" not in str(item)
            for item in second_workspace["items"]
            if item.get("event_key") in buyer_event_keys
        )
    for item in second_project:
        if item.get("field") == "buyer":
            new_state = item.get("new") or {}
            event_source_ids = {
                str(value) for value in new_state.get("buying_chain_evidence_ids", [])
            }
            if item.get("buying_chain_evidence_id"):
                event_source_ids.add(str(item["buying_chain_evidence_id"]))
            assert all(source.get("id") in event_source_ids for source in item["sources"])
    assert "Jordan Smith private roster snapshot" not in str(second_project)
    assert "jordan.smith@example.test" not in str(second_project)
    repeated_project, repeated_workspace, _, _ = read_surfaces()
    assert second_project == repeated_project
    assert second_workspace["items"] == repeated_workspace["items"]
    assert second_workspace["token"] == repeated_workspace["token"]


def test_change_event_limits_fail_closed_per_project_and_isolate_malformed_event(
    saved_db, monkeypatch
):
    from test_buying_chain import _seed_tdlr_retained_project

    from gridlens.intelligence import saved_history_privacy

    entries = []
    project_claim_counts = {}
    with saved_db.begin() as session:
        for index in range(2):
            case = list(_tdlr_case_with_contact())
            case[0] = f"TABS202602695{5 + index}"
            case[1] = f"{case[1]} {index}"
            case[4] = case[4].replace("Project: PECOS COUNTY DATA CENTER", f"Project: {case[1]}")
            project, retained, _owner = _seed_tdlr_retained_project(session, tuple(case))
            project.region_status = "ELIGIBLE"
            enrich_buying_chain(session, project.id, retained_only=True, now=NOW)
            project_claim_counts[project.id] = session.scalar(
                select(func.count())
                .select_from(BuyingChainClaim)
                .where(BuyingChainClaim.project_id == project.id)
            )
            event = session.scalar(
                select(ChangeEvent)
                .where(ChangeEvent.project_id == project.id, ChangeEvent.field_name == "buyer")
                .order_by(ChangeEvent.id.desc())
            )
            assert event is not None
            source_ids = (event.new_state or {}).get("buying_chain_evidence_ids", [])
            source_rows = [
                session.get(BuyingChainEvidence, UUID(str(source_id))) for source_id in source_ids
            ]
            entries.append(
                (
                    event,
                    {
                        "field": "buyer",
                        "prior": deepcopy(event.prior_state),
                        "new": deepcopy(event.new_state),
                        "sources": [
                            {
                                "id": str(source.id),
                                "title": source.title,
                                "url": source.url,
                                "content_hash": source.content_hash,
                            }
                            for source in source_rows
                            if source is not None
                        ],
                    },
                    "prior",
                    "new",
                )
            )

        overflow_project_id = max(project_claim_counts, key=project_claim_counts.get)
        valid_project_id = next(
            project_id for project_id in project_claim_counts if project_id != overflow_project_id
        )
        event_by_project = {entry[0].project_id: entry for entry in entries}
        overflow_entry = event_by_project[overflow_project_id]
        valid_entry = event_by_project[valid_project_id]
        overflow_event = overflow_entry[0]
        session.add(
            BuyingChainClaim(
                project_id=overflow_project_id,
                entity_key="bounded-history-overflow-fixture",
                fingerprint=sha256(b"bounded-history-overflow-fixture").hexdigest(),
                policy_version="test-v1",
                organization="Private Overflow Company",
                person_name="Private Overflow Person",
                title="Private Overflow Role",
                category="owner_developer",
                organization_relationship="DIRECT",
                person_organization_relationship="UNKNOWN",
                person_project_relationship="UNKNOWN",
                evidence_strength="Low",
                reason="Bounded history test row.",
                citations=[],
                public_contacts=[],
                observed_at=NOW,
            )
        )
        session.flush()
        immutable = deepcopy(overflow_event.new_state)

        monkeypatch.setattr(
            saved_history_privacy,
            "MAX_HISTORY_CLAIMS",
            max(project_claim_counts.values()),
        )
        single = saved_history_privacy.project_change_events_public(
            session,
            [overflow_entry],
        )
        assert single == [None]
        mixed = saved_history_privacy.project_change_events_public(
            session,
            [overflow_entry, valid_entry],
        )
        assert mixed[0] is None
        assert mixed[1] is not None
        assert any(row.get("person_name") == "Jordan Smith" for row in mixed[1]["new"]["value"])

        malformed_item = deepcopy(valid_entry[1])
        malformed_item["new"] = {"value": "legacy private person text"}
        malformed_entry = (valid_entry[0], malformed_item, "prior", "new")
        isolated = saved_history_privacy.project_change_events_public(
            session,
            [malformed_entry, valid_entry],
        )
        assert isolated[0] is None
        assert isolated[1] is not None
        assert any(row.get("person_name") == "Jordan Smith" for row in isolated[1]["new"]["value"])
        assert overflow_event.new_state == immutable


def test_noncontact_change_event_values_survive_publication_without_assuming_lists(saved_db):
    from test_buying_chain import _seed_tdlr_retained_project

    from gridlens.intelligence.saved_history_privacy import project_change_events_public

    values = (None, 7, "unchanged")
    with saved_db.begin() as session:
        project, _retained, _owner = _seed_tdlr_retained_project(session, _tdlr_case_with_contact())
        project.region_status = "ELIGIBLE"
        enrich_buying_chain(session, project.id, retained_only=True, now=NOW)
        entries = []
        for index, value in enumerate(values):
            event = ChangeEvent(
                id=index + 1,
                project_id=project.id,
                field_name="power_need",
                kind="power_need_changed",
                prior_state={"value": value},
                new_state={"value": value},
            )
            item = {
                "before_state": {"value": value},
                "after_state": {"value": value},
                "sources": [],
            }
            entries.append((event, item, "before_state", "after_state"))
        projected = project_change_events_public(session, entries)
        assert [item["before_state"]["value"] for item in projected if item] == list(values)
        assert [item["after_state"]["value"] for item in projected if item] == list(values)


def _two_person_projection_fixture(session, monkeypatch):
    """Isolate post-attribution source ownership; native attribution is tested above.

    This seam supplies two already-authorized public candidates. It is not
    evidence that arbitrary public research has native publication authority.
    """
    from test_buying_chain import _seed_tdlr_retained_project

    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence import buying_chain

    project, retained, _ = _seed_tdlr_retained_project(session, _tdlr_case_with_contact())
    project.region_status = "ELIGIBLE"
    candidates, sources, claims = [], [], []
    for index, name in enumerate(("Jordan Smith", "Casey Jones")):
        doc = PublicDocument(
            f"https://external.example/people/{index}",
            f"{name} project contact, email extra{index}@example.test, phone (512) 555-019{index}",
            f"{name} is the project manager for Example Owner at the project.",
            observed_at=NOW,
        )
        source = BuyingChainEvidence(
            project_id=project.id,
            url=doc.url,
            title=doc.title,
            excerpt=doc.text,
            content_hash=buying_chain.document_content_hash(doc),
            extraction_location=doc.extraction_location,
            observed_at=NOW,
            last_seen_at=NOW,
            project_match_reason="Exact project fixture.",
        )
        company, person = CompanyIdentity(), PersonIdentity()
        session.add_all([source, company, person])
        session.flush()
        citation = {
            "id": str(source.id),
            "url": source.url,
            "content_hash": source.content_hash,
            "supports": "organization_person_role",
            "current_support": True,
            "current_source_version_id": str(source.id),
            "quote": doc.text,
        }
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key=f"person-{index}",
            fingerprint=sha256(name.encode()).hexdigest(),
            policy_version="test-v1",
            organization="Example Owner",
            person_name=name,
            title="Project manager",
            category="owner_developer",
            organization_relationship="DIRECT",
            person_organization_relationship="DIRECT",
            person_project_relationship="DIRECT",
            evidence_strength="High",
            reason="Projection fixture",
            citations=[citation],
            public_contacts=[{"kind": "profile", "value": source.url}],
            observed_at=NOW,
        )
        session.add(claim)
        session.flush()
        session.add_all(
            [
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type="company",
                    company_identity_id=company.id,
                    reason="Fixture",
                    basis="reviewed",
                    source_evidence_id=source.id,
                    source_version_hash=source.content_hash,
                    state="current",
                ),
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type="person",
                    person_identity_id=person.id,
                    reason="Fixture",
                    basis="reviewed",
                    source_evidence_id=source.id,
                    source_version_hash=source.content_hash,
                    state="current",
                ),
            ]
        )
        candidates.append(
            {
                "id": str(claim.id),
                **_candidate_row(vars(claim)),
                "evidence": [citation],
                "public_contacts": claim.public_contacts,
            }
        )
        sources.append(source)
        claims.append(claim)
    event = ChangeEvent(
        observation_id=retained.observation_id,
        content_hash=retained.content_hash,
        kind="buyer_changed",
        project_id=project.id,
        field_name="buyer",
        buying_chain_evidence_id=sources[0].id,
        prior_state={"value": []},
        new_state={
            "value": [_candidate_row(row) for row in candidates],
            "buying_chain_evidence_ids": [str(source.id) for source in sources],
        },
        material=True,
        replay_key=sha256(b"two-person-projection-fixture").hexdigest(),
    )
    session.add(event)
    session.flush()
    monkeypatch.setattr(
        buying_chain,
        "buying_chain_views",
        lambda _session, _ids, **_kwargs: {str(project.id): {"candidates": candidates}},
    )
    item = {
        "prior": deepcopy(event.prior_state),
        "new": deepcopy(event.new_state),
        "sources": [
            {
                "id": str(source.id),
                "title": source.title,
                "url": source.url,
                "content_hash": source.content_hash,
            }
            for source in sources
        ],
    }
    return project, event, item, candidates, sources, claims


@pytest.mark.parametrize("include_ids", (False, True))
@pytest.mark.parametrize("control", ("person", "scoped_method", "global_method"))
def test_sources_follow_each_claim_through_late_controls(
    saved_db, monkeypatch, include_ids, control
):
    from gridlens.intelligence.contact_suppressions import global_method_suppression_key
    from gridlens.intelligence.saved_history_privacy import project_change_events_public

    with saved_db.begin() as session:
        project, event, item, _candidates, sources, claims = _two_person_projection_fixture(
            session, monkeypatch
        )
        old_company = CompanyIdentity()
        session.add(old_company)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=claims[0].id,
                entity_type="company",
                company_identity_id=old_company.id,
                reason="Historical owner",
                basis="reviewed",
                source_evidence_id=sources[0].id,
                source_version_hash=sources[0].content_hash,
                state="superseded",
                superseded_at=NOW,
            )
        )
        session.add(
            BuyingChainCorrection(
                project_id=project.id,
                claim_id=claims[0].id,
                expected_version=claims[0].fingerprint,
                idempotency_key="corrected-fixture-name",
                action="amend",
                values={"person_name": "Jordan Corrected"},
                reason="Historical name",
                actor="test",
            )
        )
        session.flush()
        raw = deepcopy(event.new_state)

        def read():
            return project_change_events_public(
                session, [(event, item, "prior", "new")], include_source_ids=include_ids
            )[0]

        before = read()
        assert before is not None
        assert {row["person_name"] for row in before["new"]["value"]} == {
            "Jordan Smith",
            "Casey Jones",
        }
        assert {source["url"] for source in before["sources"]} == {source.url for source in sources}
        assert "@example.test" not in str(before) and "(512) 555-019" not in str(before)
        if control == "person":
            scope = "person"
            key = person_suppression_key(old_company.id, "Jordan Corrected")
        elif control == "scoped_method":
            scope = "method"
            key = method_suppression_key(
                old_company.id, "Jordan Corrected", "profile", sources[0].url
            )
        else:
            scope = "method"
            key = global_method_suppression_key("profile", sources[0].url)
        record_contact_suppression(
            session,
            scope=scope,
            subject_key=key,
            action="suppress",
            expected_version=0,
            reason="Exact historical control",
            actor="test",
            idempotency_key="two-person-control",
        )
        after = read()
        assert after is not None
        assert sources[0].url not in str(after)
        assert sources[1].url in str(after)
        assert "Casey Jones" in str(after)
        if control == "person":
            assert "Jordan Smith" not in str(after)
            assert {row["person_name"] for row in after["new"]["value"]} == {"Casey Jones"}
        else:
            assert "Jordan Smith" in str(after)
        assert all(("id" in source) == include_ids for source in after["sources"])
        assert event.new_state == raw
        assert item["new"] == raw


def test_generic_person_provenance_and_forged_keys_cannot_authorize_history(saved_db, monkeypatch):
    from gridlens.intelligence.saved_history_privacy import (
        project_change_events_public,
        project_saved_history_privacy,
    )

    with saved_db.begin() as session:
        project, event, item, candidates, sources, claims = _two_person_projection_fixture(
            session, monkeypatch
        )
        candidates.clear()  # No current authorized public candidate exists.
        item["_validated_event_claim_ids"] = [str(claim.id) for claim in claims]
        item["new"]["_validated_event_claim_ids"] = item["_validated_event_claim_ids"]
        projected = project_change_events_public(session, [(event, item, "prior", "new")])[0]
        assert projected is not None and projected["new"]["value"] == []
        assert projected["sources"] == []
        assert "Jordan Smith" not in str(projected) and "Casey Jones" not in str(projected)
        old = CompanyIdentity()
        session.add(old)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=claims[0].id,
                entity_type="company",
                company_identity_id=old.id,
                reason="Unproved ambiguous history",
                basis="reviewed",
                source_evidence_id=sources[0].id,
                source_version_hash=sources[0].content_hash,
                state="superseded",
                superseded_at=NOW,
            )
        )
        session.flush()
        forged = {
            "project_id": str(project.id),
            "saved_card": {
                "_validated_event_claim_ids": [str(claims[0].id)],
                "contacts": [{"claim_id": str(claims[0].id), "name": "Jordan Smith"}],
            },
        }
        assert project_saved_history_privacy(session, forged)["saved_card"]["contacts"] == []


def test_conflicting_current_identities_cannot_use_event_lineage_exception(saved_db, monkeypatch):
    from gridlens.intelligence.saved_history_privacy import project_change_events_public

    with saved_db.begin() as session:
        _project, event, item, _candidates, _sources, claims = _two_person_projection_fixture(
            session, monkeypatch
        )
        # Both currently admitted candidates claim the same retained entity
        # lineage but link to different canonical people and companies.
        claims[1].entity_key = claims[0].entity_key
        session.flush()
        raw = deepcopy(event.new_state)
        projected = project_change_events_public(session, [(event, item, "prior", "new")])[0]
        assert projected is not None
        assert projected["new"]["value"] == [] and projected["sources"] == []
        assert "Jordan Smith" not in str(projected) and "Casey Jones" not in str(projected)
        assert event.new_state == raw


def test_organization_withdrawal_sources_keep_exact_historical_controls(saved_db, monkeypatch):
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain import document_content_hash
    from gridlens.intelligence.saved_history_privacy import project_change_events_public

    with saved_db.begin() as session:
        _project, event, item, candidates, sources, claims = _two_person_projection_fixture(
            session, monkeypatch
        )
        # Separate organization-only causal histories, no current role remains.
        candidates.clear()
        for index, claim in enumerate(claims):
            claim.person_name = None
            claim.title = None
            claim.organization = f"Organization {index}"
            claim.public_contacts = []
            source = sources[index]
            source.title = f"Organization {index} project source"
            source.excerpt = f"Organization {index} is the project contractor."
            source.content_hash = document_content_hash(
                PublicDocument(
                    source.url,
                    source.title,
                    source.excerpt,
                    observed_at=NOW,
                )
            )
            claim.citations = [
                {
                    "id": str(source.id),
                    "url": source.url,
                    "content_hash": source.content_hash,
                    "supports": "project_organization",
                    "quote": source.excerpt,
                }
            ]
        prior_rows = [_candidate_row(vars(claim)) for claim in claims]
        event.prior_state = {"value": prior_rows}
        event.new_state = {**event.new_state, "value": []}
        item["prior"] = deepcopy(event.prior_state)
        item["new"] = deepcopy(event.new_state)
        item["sources"] = [
            {
                "id": str(source.id),
                "url": source.url,
                "title": source.title,
                "content_hash": source.content_hash,
            }
            for source in sources
        ]
        session.flush()
        original = deepcopy(event.new_state)

        def read():
            return project_change_events_public(session, [(event, item, "prior", "new")])[0]

        before = read()
        assert before is not None and before["new"]["value"] == []
        assert {source["url"] for source in before["sources"]} == {source.url for source in sources}
        company_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claims[0].id,
                BuyingChainIdentityLink.entity_type == "company",
            )
        )
        record_contact_suppression(
            session,
            scope="company",
            subject_key=company_suppression_key(company_link.company_identity_id),
            action="suppress",
            expected_version=0,
            reason="Historical organization privacy",
            actor="test",
            idempotency_key="withdrawn-company-control",
        )
        after = read()
        assert after is not None and after["new"]["value"] == []
        assert sources[0].url not in str(after)
        assert sources[1].url in str(after)
        assert event.new_state == original


@pytest.mark.parametrize("malformation", ("dict", "list", "bad_source_id", "oversized_sources"))
def test_malformed_events_are_isolated_on_actual_read_routes(saved_db, monkeypatch, malformation):
    from gridlens.intelligence.saved_history_privacy import MAX_HISTORY_METHODS

    with saved_db.begin() as session:
        project, valid, _item, _candidates, sources, _claims = _two_person_projection_fixture(
            session, monkeypatch
        )
        broken = deepcopy(valid.new_state)
        if malformation in {"dict", "list"}:
            broken["value"][0]["organization"] = {} if malformation == "dict" else []
        elif malformation == "bad_source_id":
            broken["buying_chain_evidence_ids"] = [str(sources[0].id), "not-a-uuid"]
        else:
            broken["buying_chain_evidence_ids"] = [str(sources[0].id)] * (MAX_HISTORY_METHODS + 1)
        bad = ChangeEvent(
            observation_id=valid.observation_id,
            content_hash=valid.content_hash,
            kind="buyer_changed",
            project_id=project.id,
            field_name="buyer",
            buying_chain_evidence_id=sources[0].id,
            prior_state=deepcopy(valid.prior_state),
            new_state=broken,
            material=True,
            replay_key=sha256(malformation.encode()).hexdigest(),
        )
        session.add(bad)
        session.flush()
        bad_id, valid_id, project_id = bad.id, valid.id, project.id
        bad_snapshot = deepcopy(bad.new_state)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", saved_db)
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(f"/api/projects/{project_id}/changes")
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    assert {row["person_name"] for row in response.json()[0]["new"]["value"]} == {
        "Jordan Smith",
        "Casey Jones",
    }
    workspace = client.get("/api/opportunities/workspace/changes")
    assert workspace.status_code == 200, workspace.text
    assert f"change:{bad_id}" not in {item["event_key"] for item in workspace.json()["items"]}
    assert f"change:{valid_id}" in {item["event_key"] for item in workspace.json()["items"]}
    metadata = client.get("/api/changes")
    assert metadata.status_code == 200, metadata.text
    assert len(metadata.json()) == 2
    assert sum(bool(item["sources"]) for item in metadata.json()) == 1
    with saved_db() as session:
        assert session.get(ChangeEvent, bad_id).new_state == bad_snapshot
