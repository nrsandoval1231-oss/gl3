"""Frozen source facts use the existing canonical account and cohort SQL."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from gridlens.intelligence.customer_results import group_metadata, groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    ChangeEvent,
    CompanyIdentity,
    Evidence,
    Project,
)

pytest_plugins = ["test_saved_browse"]


def test_customer_intelligence_is_account_wide_and_ranked_before_pagination(saved_db):
    from test_saved_browse import seed

    seed(saved_db, count=3, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.project_id)
        ).all()
        identities = [CompanyIdentity(id=uuid4()), CompanyIdentity(id=uuid4())]
        session.add_all(identities)
        session.flush()
        for index, row in enumerate(rows):
            company = identities[0 if index < 2 else 1]
            row.compact = {
                **row.compact,
                "project_metadata": {"sector": "data_centers", "title": str(row.project_id)},
                "customer_facts": [
                    {
                        "version": "customer-facts-v1",
                        "project_id": str(row.project_id),
                        "capacity_claims": [],
                        "timeline_claims": [],
                        "commissioning_inputs": [],
                    }
                ],
                "customer_priority": {"score": 90 if index == 2 else 10, "confidence": 80},
            }
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=company.id,
                    project_id=row.project_id,
                    organization_name="Zulu" if index == 2 else "Alpha",
                    role="owner_developer",
                )
            )
    with saved_db() as session:
        first = groups(session, limit=1)
        assert first["items"][0]["name"] == "Zulu"
        second = groups(session, limit=1, offset=1, token=first["cohort_token"])
        account = second["items"][0]
        assert account["name"] == "Alpha"
        assert account["project_count"] == 2
        intelligence = account["commercial_intelligence"]
        assert intelligence["version"] == "customer-intelligence-v1"
        assert intelligence["capacity"]["status"] in {"unknown", "insufficient_data"}
        detail = group_metadata(session, account["id"])
        assert detail["commercial_intelligence"] == intelligence


def test_customer_development_carries_evidence_and_hides_contact_tokens(saved_db):
    from test_saved_browse import seed

    seed(saved_db, count=1, histories=1)
    with saved_db.begin() as session:
        project = session.scalar(select(Project))
        evidence = session.scalar(select(Evidence))
        session.add(
            ChangeEvent(
                observation_id=evidence.observation_id,
                content_hash=evidence.content_hash,
                kind="capacity_changed",
                project_id=project.id,
                evidence_id=evidence.id,
                field_name="capacity",
                prior_state={"value": "50"},
                new_state={"value": "100", "quote": "Contact secret@example.invalid"},
                material=True,
                replay_key=uuid4().hex,
                created_at=datetime.now(UTC),
            )
        )
        identity = CompanyIdentity(id=uuid4())
        session.add(identity)
        session.flush()
        identity_id = identity.id
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        row = session.scalar(select(BrowseRow).where(BrowseRow.generation_id == generation.id))
        row.compact = {**row.compact, "project_metadata": {"sector": "data_centers"}}
        session.add(
            BrowseCustomerMembership(
                generation_id=generation.id,
                company_identity_id=identity_id,
                project_id=row.project_id,
                organization_name="Orion",
                role="owner_developer",
            )
        )
    with saved_db() as session:
        summary = groups(session)["items"][0]["commercial_intelligence"]
        assert summary["recent_developments"][0]["summary"] == "Build capacity revised"
        assert summary["recent_developments"][0]["evidence_id"] == str(evidence.id)
        assert "secret@example.invalid" not in str(summary)


def test_updating_snapshot_withholds_potentially_withdrawn_commercial_facts(saved_db):
    from test_saved_browse import seed

    from gridlens.domain.customer_intelligence import extract_customer_facts

    seed(saved_db, count=1, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        row = session.scalar(select(BrowseRow).where(BrowseRow.generation_id == generation.id))
        identity = CompanyIdentity(id=uuid4())
        session.add(identity)
        session.flush()
        facts = extract_customer_facts(
            "Orion campus development capacity is 100 MW.",
            project_id=str(row.project_id),
            source={
                "url": "https://example.test/announcement",
                "authority": "primary",
                "verification_status": "verified",
                "observed_at": "2026-11-12",
                "evidence_id": str(uuid4()),
                "content_hash": "a" * 64,
            },
        )
        row.compact = {
            **row.compact,
            "project_metadata": {"sector": "data_centers"},
            "customer_facts": [facts],
        }
        session.add(
            BrowseCustomerMembership(
                generation_id=generation.id,
                company_identity_id=identity.id,
                project_id=row.project_id,
                organization_name="Orion",
                role="owner_developer",
            )
        )
    with saved_db() as session:
        generation = current_generation(session)
        current = groups(session, selected_generation=generation)
        assert current["items"][0]["commercial_intelligence"]["capacity"]["claims"]
        generation.serving_stale = True
        stale = groups(session, selected_generation=generation)
        summary = stale["items"][0]["commercial_intelligence"]
        assert not summary["capacity"]["claims"]
        assert any("refresh" in reason.lower() for reason in summary["limitations"])


def test_named_professional_without_methods_uses_existing_account_scope_and_guard(
    saved_db, monkeypatch
):
    """Selection test: the central native authorization boundary is an explicit seam."""
    from test_saved_browse import seed

    from gridlens.intelligence import project_contact_actions

    seed(saved_db, count=1, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        row = session.scalar(select(BrowseRow).where(BrowseRow.generation_id == generation.id))
        identity = CompanyIdentity(id=uuid4())
        session.add(identity)
        session.flush()
        owner_id = str(identity.id)
        row.compact = {
            **row.compact,
            "project_metadata": {"sector": "data_centers"},
            "contact_actions": [],
            "contact_people": [
                {
                    "record_type": "contact_person",
                    "company_identity_id": owner_id,
                    "person_identity_id": str(uuid4()),
                    "name": "Alice Example",
                    "title": "Commissioning Director",
                    "company": "Orion",
                    "responsibility": "Verified organizational responsibility",
                    "source_url": "https://example.test/team",
                }
            ],
        }
        session.add(
            BrowseCustomerMembership(
                generation_id=generation.id,
                company_identity_id=identity.id,
                project_id=row.project_id,
                organization_name="Orion",
                role="owner_developer",
            )
        )
    calls = []

    def authorized(_session, records):
        calls.append(list(records))
        return [record for record in records if record.get("company_identity_id") == owner_id]

    monkeypatch.setattr(project_contact_actions, "filter_project_contact_records", authorized)
    with saved_db() as session:
        contact_project = groups(session)["items"][0]["account_contact_project"]
        assert contact_project is not None
        assert contact_project["contact"] == []
        assert contact_project["contact_people"][0]["name"] == "Alice Example"
        assert calls and any(
            record.get("record_type") == "contact_person" for records in calls for record in records
        )
    # Native authorization remains authoritative; cached names alone publish nothing.
    monkeypatch.setattr(project_contact_actions, "filter_project_contact_records", lambda *_: [])
    with saved_db() as session:
        assert groups(session)["items"][0]["account_contact_project"] is None
