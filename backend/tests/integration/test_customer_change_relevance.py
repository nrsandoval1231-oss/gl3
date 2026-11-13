"""First-seen historical facts remain history, not recent customer revisions."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from gridlens.intelligence.saved_browse import (
    _recent_material_revisions,
    current_generation,
    rebuild,
)
from gridlens.persistence.models import (
    BrowseRow,
    BuyingChainEvidence,
    ChangeEvent,
    Evidence,
    NeedObservation,
    PowerNeed,
)

pytest_plugins = ["test_saved_browse"]


def test_all_material_fields_require_prior_facts_and_source_recency(saved_db):
    from test_saved_browse import seed

    now = datetime.now(UTC)
    today = now.date()
    claim = {"claims": [{"value_mw": "50", "qualifier": "up_to"}]}
    revised = {"claims": [{"value_mw": "50", "qualifier": "exact"}]}
    cases = [
        ("phase", None, "construction", "today", False),
        ("phase", "Unknown", "construction", "today", False),
        ("buyer", [], [{"organization": "Owner"}], "today", False),
        ("contractor", [], [{"organization": "Builder"}], "today", False),
        ("power_need", [], [{"activity": "construction"}], "today", False),
        ("utility_timing", [], ["2027-01-01"], "today", False),
        ("capacity", {"claims": []}, claim, "today", False),
        ("build_timing", {"claims": []}, {"claims": [{"start": "2027"}]}, "today", False),
        ("capacity", claim, revised, "old", False),
        ("capacity", claim, revised, "future", False),
        ("capacity", claim, revised, "unknown", False),
        ("capacity", claim, revised, "future_publication", False),
        ("capacity", claim, revised, "mismatched_evidence", False),
        ("capacity", claim, claim, "today", False),
        ("capacity", claim, revised, "publication_fallback", True),
        ("phase", "project_formation", "construction", "today", True),
        (
            "buyer",
            [{"organization": "Prior owner"}],
            [{"organization": "New owner"}],
            "buying_publication",
            True,
        ),
        ("power_need", [{"active": True}], [{"active": False}], "today", True),
        ("utility_timing", ["2027-01-01"], ["2027-04-01"], "today", True),
        ("capacity", claim, {"claims": []}, "today", True),
    ]
    need_ids = seed(saved_db, count=len(cases), histories=1)
    expected = set()
    project_ids = set()
    with saved_db.begin() as session:
        for need_id, (field, before, after, dating, eligible) in zip(need_ids, cases, strict=True):
            need = session.get(PowerNeed, need_id)
            project_ids.add(need.project_id)
            evidence = session.scalar(
                select(Evidence)
                .join(NeedObservation, NeedObservation.observation_id == Evidence.observation_id)
                .where(NeedObservation.need_id == need_id)
            )
            evidence.published_at = today
            source_date = today
            buying_id = None
            evidence_id = evidence.id
            content_hash = evidence.content_hash
            if dating == "old":
                source_date = today - timedelta(days=91)
            elif dating == "future":
                source_date = today + timedelta(days=1)
            elif dating != "today":
                source_date = None
                if dating in {"unknown", "buying_publication"}:
                    evidence.published_at = None
                elif dating == "future_publication":
                    evidence.published_at = today + timedelta(days=1)
                elif dating == "mismatched_evidence":
                    content_hash = "f" * 64
                if dating == "buying_publication":
                    buying = BuyingChainEvidence(
                        project_id=need.project_id,
                        url="https://example.test/ownership",
                        title="Ownership revision",
                        excerpt="New owner replaces prior owner.",
                        content_hash="a" * 64,
                        extraction_location="body",
                        published_at=today,
                        observed_at=now,
                        last_seen_at=now,
                        project_match_reason="Test project relation",
                    )
                    session.add(buying)
                    session.flush()
                    buying_id, evidence_id = buying.id, None
            event = ChangeEvent(
                observation_id=evidence.observation_id,
                content_hash=content_hash,
                kind=f"{field}_changed",
                project_id=need.project_id,
                evidence_id=evidence_id,
                buying_chain_evidence_id=buying_id,
                field_name=field,
                prior_state={"value": before, "evidence_refs": []},
                new_state={"value": after, "evidence_refs": [{"evidence_id": str(evidence.id)}]},
                material=True,
                source_date=source_date,
                created_at=now,
            )
            session.add(event)
            session.flush()
            if eligible:
                expected.add(event.id)
    with saved_db() as session:
        revisions = _recent_material_revisions(session, project_ids, as_of=now)
        assert {item["id"] for item in revisions} == expected
        assert all(item["effective_source_date"] == today for item in revisions)
        assert len(session.scalars(select(ChangeEvent)).all()) == len(cases)


def test_initial_events_cannot_displace_a_recent_dated_revision(saved_db):
    from test_saved_browse import seed

    need_id = seed(saved_db, count=1, histories=1)[0]
    now = datetime.now(UTC)
    with saved_db.begin() as session:
        need = session.get(PowerNeed, need_id)
        evidence = session.scalar(select(Evidence))
        revision = ChangeEvent(
            observation_id=evidence.observation_id,
            content_hash=evidence.content_hash,
            kind="capacity_changed",
            project_id=need.project_id,
            evidence_id=evidence.id,
            field_name="capacity",
            prior_state={"value": "50"},
            new_state={"value": "100"},
            material=True,
            source_date=now.date(),
            created_at=now - timedelta(minutes=1),
        )
        session.add(revision)
        for _ in range(5):
            session.add(
                ChangeEvent(
                    observation_id=evidence.observation_id,
                    content_hash=evidence.content_hash,
                    kind="capacity_changed",
                    project_id=need.project_id,
                    evidence_id=evidence.id,
                    field_name="capacity",
                    prior_state={"value": {"claims": []}},
                    new_state={"value": {"claims": [{"value_mw": "100"}]}},
                    material=True,
                    source_date=now.date(),
                    created_at=now,
                )
            )
        session.flush()
        project_id, revision_id = need.project_id, revision.id
    with saved_db() as session:
        events = _recent_material_revisions(session, {project_id}, as_of=now)
        assert [event["id"] for event in events] == [revision_id]


def test_actual_retained_announcements_do_not_claim_recent_revisions(saved_db):
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.intelligence.customer_results import groups
    from gridlens.persistence.models import Job, Project, Source

    root = Path(__file__).resolve().parents[3]
    retained, _held = retained_records(root / "eval/customer-commercial-v1")
    records = [
        record
        for record in retained
        if {"sources/databank.json", "sources/cyrusone.json"}
        & set(record["retained_company_project"]["source_files"])
    ]
    assert len(records) == 2
    source = {
        "id": SOURCE_ID,
        "publisher": "retained offline public documents",
        "endpoint": "https://offline.invalid/retained",
        "family": FAMILY,
        "geography": "United States",
        "industries": ["data centers"],
        "retrieval_method": RETRIEVAL_METHOD,
        "cadence_hours": 24,
        "enabled": False,
        "registry_enabled": False,
    }
    worker = "customer-change-relevance-test"
    with saved_db.begin() as session:
        session.add(Source(**source))
        session.flush()
        job = Job(
            source_id=SOURCE_ID,
            status="running",
            lease_owner=worker,
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    with saved_db() as session:
        counts = process_records(session, job_id, worker, 1, source, records, allow_model=False)
        assert counts["new"] == 2 and counts["changed"] == 0
    with saved_db.begin() as session:
        for project in session.scalars(select(Project)):
            evidence = next(
                item
                for item in session.scalars(select(Evidence))
                if item.provenance["retained_company_project"]["project_name"] == project.name
            )
            enrich_buying_chain(
                session, project.id, retained_only=True, retained_target_evidence_id=evidence.id
            )
    with saved_db() as session:
        history = {
            event.id: (deepcopy(event.prior_state), deepcopy(event.new_state), event.source_date)
            for event in session.scalars(select(ChangeEvent))
        }
        initial_facts = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name.in_(["capacity", "build_timing"]))
        ).all()
        assert {(event.field_name, event.source_date) for event in initial_facts} >= {
            ("capacity", date(2024, 9, 10)),
            ("build_timing", date(2025, 7, 30)),
        }
        assert all(event.prior_state["value"] == {"claims": []} for event in initial_facts)
        assert {event.source_date for event in initial_facts} == {
            date(2024, 9, 10),
            date(2025, 7, 30),
        }
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow).where(BrowseRow.generation_id == generation.id)
        ).all()
        assert len(rows) == 2
        for row in rows:
            assert row.compact["customer_developments"] == []
            assert row.compact["customer_priority"]["components"]["material_changes"] == 0
            assert row.compact["customer_facts"]
        accounts = groups(session, sector="data_centers", canonical_only=True)["items"]
        assert {account["name"] for account in accounts} == {"DataBank", "CyrusOne"}
        for account in accounts:
            intel = account["commercial_intelligence"]
            assert intel["recent_developments"] == []
            assert "revised" not in intel["recommended_next_action"].casefold()
        assert history == {
            event.id: (event.prior_state, event.new_state, event.source_date)
            for event in session.scalars(select(ChangeEvent))
        }


def test_recent_qualifier_and_operational_revisions_retain_the_snapshot_bonus(saved_db):
    from test_saved_browse import seed

    need_id = seed(saved_db, count=1, histories=1)[0]
    with saved_db.begin() as session:
        need = session.get(PowerNeed, need_id)
        evidence = session.scalar(select(Evidence))
        evidence.published_at = datetime.now(UTC).date()
        for field, before, after in (
            (
                "capacity",
                {"value_mw": "50", "qualifier": "up_to"},
                {"value_mw": "50", "qualifier": "exact"},
            ),
            (
                "build_timing",
                {"event_type": "operational_target", "start": "2027-04-01"},
                {"event_type": "operational_target", "start": "2027-07-01"},
            ),
        ):
            session.add(
                ChangeEvent(
                    observation_id=evidence.observation_id,
                    content_hash=evidence.content_hash,
                    kind=f"{field}_changed",
                    project_id=need.project_id,
                    evidence_id=evidence.id,
                    field_name=field,
                    prior_state={"value": {"claims": [before]}},
                    new_state={"value": {"claims": [after]}},
                    material=True,
                    source_date=None,
                )
            )
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        generation = current_generation(session)
        row = session.scalar(select(BrowseRow).where(BrowseRow.generation_id == generation.id))
        assert row.compact["customer_priority"]["components"]["material_changes"] == 10
        assert {event["summary"] for event in row.compact["customer_developments"]} == {
            "Build capacity revised",
            "Operational target revised",
        }
        assert all(
            event["source_date"] == evidence.published_at.isoformat()
            for event in row.compact["customer_developments"]
        )
