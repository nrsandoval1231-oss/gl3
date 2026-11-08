"""Persisted research claims flow into the public project result brief."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from test_pursuit_evidence import research_db as _isolated_research_db
from test_pursuit_evidence import seed

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.project_results import page as project_result_page
from gridlens.intelligence.project_state import current_research_state
from gridlens.intelligence.research_evidence import retain_research_document
from gridlens.intelligence.saved_browse import rebuild
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.models import PowerNeed, Project


@pytest.fixture
def research_db():
    yield from _isolated_research_db.__wrapped__()


def test_retained_research_claim_reaches_project_result_commercial_brief(research_db):
    factory, source, job_id = research_db
    with factory.kw["bind"].begin() as connection:
        install(connection)
    need_id = seed(factory, source, job_id)
    url = "https://www.federalregister.gov/documents/orion/"
    quote = "Orion Data Center construction requires 12 MW."
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        accepted = retain_research_document(
            session,
            project,
            need,
            PublicDocument(
                url,
                "Orion Data Center construction status",
                "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway.\n"
                + quote,
                date.today(),
                datetime.now(UTC),
                "public project update",
            ),
        )
        assert accepted["disposition"] == "ACCEPTED", accepted.get("reason") or accepted
        state = current_research_state(session, project.id, need.id)[str(need.id)]
        activity = need.activity_key
        assert state["activity_load_mw"]["status"] == "SUPPORTED"
        assert state["activity_load_mw"]["value"] == "12"
        assert need.required_mw is None
        assert need.tier == "Signal"

    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        response = project_result_page(session, need_id=UUID(str(need_id)), limit=1)

    assert response["total"] == 1
    brief = response["items"][0]["commercial_brief"]
    assert brief["power_need"]["status"] == "supported"
    assert brief["power_need"]["value"] == "12"
    assert brief["power_need"]["unit"] == "MW"
    assert brief["power_need"]["scope"] == activity
    assert brief["power_need"]["amount_class"] == "documented"
    assert any(
        "temporary rental equipment need remains unconfirmed" in value
        for value in brief["limitations"]
    )
    assert any(source_ref["url"] == url for source_ref in brief["sources"])
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need.required_mw is None


def test_retained_campus_capacity_does_not_become_activity_power_need(research_db):
    factory, source, job_id = research_db
    with factory.kw["bind"].begin() as connection:
        install(connection)
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        accepted = retain_research_document(
            session,
            project,
            need,
            PublicDocument(
                "https://www.federalregister.gov/documents/orion-campus/",
                "Orion Data Center construction status",
                "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway.\n"
                "Orion Data Center campus capacity requires 400 MW.",
                date.today(),
                datetime.now(UTC),
                "public project update",
            ),
        )
        assert accepted["disposition"] == "ACCEPTED", accepted.get("reason") or accepted
        state = current_research_state(session, project.id, need.id)[str(need.id)]
        assert state["activity_load_mw"]["status"] == "UNKNOWN"
        assert need.required_mw is None

    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        response = project_result_page(session, need_id=UUID(str(need_id)), limit=1)
    assert response["total"] == 1
    power_need = response["items"][0]["commercial_brief"]["power_need"]
    assert power_need["status"] == "unknown"
    assert power_need["value"] is None
