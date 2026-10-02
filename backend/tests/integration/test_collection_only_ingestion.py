import hashlib
import importlib.util
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.api.app import app
from gridlens.ingestion.service import _reported_mw, news_power_activity, process_job
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


def test_reported_mw_uses_structured_domain_match_not_first_quote_number():
    assessment = {
        "demand_quote": "Campus capacity is 200 MW, but construction requires about 42 MW.",
        "demand_mw": "about 42 MW",
    }
    assert _reported_mw(assessment) == "about 42 MW"


def test_signal_activity_is_derived_from_the_validated_event_action():
    assert news_power_activity({"tier": "Signal", "action": "opens"}) == "operations"
    assert news_power_activity({"tier": "Signal", "action": "builds"}) == "construction"
    assert news_power_activity({"tier": "Signal", "action": "will be built"}) == "construction"
    assert news_power_activity({"tier": "Signal", "action": "announces"}) is None


@pytest.fixture
def db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test"))
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "Refusing to reset application database"
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="mjbizdaily-news",
                publisher="MJBizDaily",
                endpoint="https://mjbizdaily.com/feed/",
                family="news",
                geography="US-focused with international coverage",
                industries=["cannabis", "energy"],
                retrieval_method="publisher-rss",
                cadence_hours=1,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id="mjbizdaily-news",
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield engine, factory, job_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def record(summary: str = "A company announces a cultivation facility", guid: str = "first-guid"):
    # Publisher GUID changes do not replace the canonical item URL identity.
    return {
        "document_number": "https://mjbizdaily.com/news/cultivation-facility/",
        "title": "A company announces a cultivation facility",
        "abstract": summary,
        "publication_date": "2026-09-25",
        "html_url": "https://mjbizdaily.com/news/cultivation-facility/",
        "source_hash": hashlib.sha256(summary.encode()).hexdigest(),
        "extraction_location": "RSS item title and description/summary",
    }


def test_collection_replay_and_changed_version_never_create_signals(db, monkeypatch):
    _, factory, job_id = db
    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [record()])
    with factory() as session:
        first = process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "mjbizdaily-news", "retrieval_method": "publisher-rss"},
        )
    assert first["new"] == 1 and first["signals"] == 0
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [record(guid="corrected-guid")])
    with factory() as session:
        replay = process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "mjbizdaily-news", "retrieval_method": "publisher-rss"},
        )
    assert replay["unchanged"] == 1
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [record("A company expands its cultivation facility", "revised-guid")],
    )
    with factory() as session:
        changed = process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "mjbizdaily-news", "retrieval_method": "publisher-rss"},
        )
    assert changed["changed"] == 1 and changed["signals"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0
        interpretation = session.scalar(select(Interpretation))
        assert interpretation and interpretation.status == "rejected"
        assert interpretation.assessment and interpretation.assessment["decision"] == "rejected"
        assert interpretation.evaluator_version


def _project_record(
    summary: str = "", title: str = "Atlas begins construction at Atlas Mesa data center in Texas"
):
    url = "https://dcd.example/news/atlas-mesa/"
    return {
        "document_number": url,
        "title": title,
        "abstract": summary,
        "publication_date": "2026-09-25",
        "html_url": url,
        "source_hash": hashlib.sha256(f"{title}|{summary}".encode()).hexdigest(),
        "extraction_location": "RSS item title and description/summary",
    }


def test_applied_digital_news_is_retained_as_context_without_standalone_need(db, monkeypatch):
    _, factory, _ = db
    job_id = _rss_source_job(factory, "applied-digital-news", "Applied Digital News")
    import gridlens.ingestion.service as service

    title = "Applied Digital reveals $3.2bn Delta Forge 2 AI data center will be built in Alabama"
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: [_project_record("Operations could start by 2028", title)],
    )
    with factory() as session:
        counts = service.process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "applied-digital-news", "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        interpretation = session.scalar(select(Interpretation))
        need = session.scalar(select(PowerNeed))
        project_count = session.scalar(select(func.count()).select_from(Project))
        assert interpretation and interpretation.status == "accepted"
        assert interpretation.assessment["action"] == "will be built"
        assert interpretation.assessment["power_activity"] == "construction"
        assert interpretation.assessment["admission_status"] == "supplement_unmatched"
        assert need is None and project_count == 0
        assert counts["signals"] == 0


def test_news_identity_does_not_merge_distinct_sites_for_same_company_and_state():
    from gridlens.ingestion.service import _news_identity_key

    assessment = {"subject": "Atlas", "location": "Texas", "action": "construction"}
    north = _news_identity_key(
        "Atlas starts construction at North Yard data center in Texas",
        "",
        "dcd-news",
        "north",
        assessment,
    )
    south = _news_identity_key(
        "Atlas starts construction at South Yard data center in Texas",
        "",
        "utility-dive-news",
        "south",
        assessment,
    )
    assert north != south


@pytest.mark.parametrize(
    ("family", "method", "activity", "title", "abstract", "expected"),
    [
        (
            "official-utility-filings",
            "utility-docket",
            "utility-service",
            "Commission approves utility service agreement for Atlas project substation",
            "Atlas site, Denver, CO; dated energization milestone.",
            True,
        ),
        (
            "temporary-power-procurement",
            "public-procurement",
            "temporary-power",
            "Request for proposal: temporary generator rental for Atlas project site",
            "Atlas site, Denver, CO; bid due October 18.",
            True,
        ),
        (
            "official-utility-filings",
            "utility-docket",
            "utility-service",
            "Utility large-load service policy for Atlas project",
            "Atlas site, Denver, CO; applies to future applications.",
            False,
        ),
    ],
)
def test_authoritative_utility_and_solicitation_admission_persists_and_displays(
    db, monkeypatch, family, method, activity, title, abstract, expected
):
    from gridlens.api import app as api_module
    from gridlens.domain.signal_admission import admit_standalone
    from gridlens.persistence.models import NeedObservation

    _, factory, _ = db
    source_id = f"synthetic-{method}-{expected}"
    digest = "a" * 64
    with factory.begin() as session:
        source = Source(
            id=source_id,
            publisher="Official test authority",
            endpoint=f"https://authority.example/{source_id}",
            family=family,
            geography="Colorado",
            industries=["data centers"],
            retrieval_method=method,
            health={},
        )
        session.add(source)
        session.flush()
        project = Project(
            identity_key=f"{source_id}:atlas",
            name="Atlas project",
            location="Atlas site, Denver, CO",
            source_id=source_id,
            external_id="atlas",
            asset_type="data_center",
            identity_facts={"site": "Atlas site, Denver, CO"},
        )
        session.add(project)
        session.flush()
        observation = Observation(
            source_id=source_id,
            external_id="filing-1",
            title=title,
            abstract=abstract,
            published_at=date(2026, 9, 20),
            url=f"https://authority.example/{source_id}/filing-1",
            content_hash=digest,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=digest,
            title=title,
            abstract=abstract,
            url=observation.url,
            published_at=date(2026, 9, 20),
            extraction_location="official filing title and abstract",
        )
        session.add(evidence)
        session.flush()
        assessment = {
            "decision": "accepted",
            "tier": "Signal",
            "subject": "Atlas project",
            "location": "Atlas site, Denver, CO",
            "reason": "Official dated project-specific activity.",
            "power_activity": activity,
            "project_identity_key": project.identity_key,
            "semantic_hash": digest,
            "evidence_hash": digest,
        }
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=digest,
                evaluator_version="integration-test",
                assessment=assessment,
                status="accepted",
            )
        )
        admission = admit_standalone(
            source_id=source_id,
            family=family,
            retrieval_method=method,
            accepted=True,
            activity=activity,
            title=title,
            abstract=abstract,
            dated=True,
            citation_url=observation.url,
            identified_project=True,
        )
        if expected:
            need = PowerNeed(
                project_id=project.id,
                activity_key=activity,
                tier="Signal",
                rationale=assessment["reason"],
                admission_basis=admission.as_basis(source_id, digest),
                required_mw=None,
                supply="Unknown",
                active=True,
            )
            session.add(need)
            session.flush()
            session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
    monkeypatch.setattr(api_module, "SessionLocal", factory)
    cards = api_module.opportunities(tier="Signal")
    if expected:
        assert len(cards) == 1
        assert cards[0]["signal_admission_origin"] in {
            "Official utility filing",
            "Temporary-power solicitation",
        }
    else:
        assert cards == []


def _rss_source_job(factory, source_id: str, publisher: str):
    with factory.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher=publisher,
                endpoint=f"https://{source_id}.example/feed/",
                family="news",
                geography="United States",
                industries=["data centers"],
                retrieval_method="publisher-rss",
                cadence_hours=1,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=source_id,
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        return job.id


def test_news_prospect_claim_is_preserved_but_does_not_create_an_opportunity(db, monkeypatch):
    _, factory, _ = db
    job_id = _rss_source_job(factory, "mixed-mw-news", "Mixed MW News")
    import gridlens.ingestion.service as service

    summary = (
        "Atlas Mesa data center campus capacity is 200 MW, but Atlas Mesa data center "
        "construction requires about 42 MW. Power supply for Atlas Mesa data center "
        "construction is delayed."
    )
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_project_record(summary)])
    with factory() as session:
        service.process_job(
            session,
            job_id,
            "test",
            1,
            {"id": "mixed-mw-news", "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        interpretation = session.scalar(select(Interpretation))
        assert need is None
        assert interpretation and interpretation.assessment["tier"] == "Prospect"
        assert interpretation.assessment["admission_status"] == "supplement_unmatched"
        assert interpretation and interpretation.assessment["demand_mw"] == "about 42 MW"


def test_supported_news_need_change_is_attributed_once_and_unrelated_evidence_stays_quiet(db):
    _, factory, _ = db
    from gridlens.domain.signal_admission import admit_standalone
    from gridlens.ingestion.registry import load_registry
    from gridlens.ingestion.service import assess_retained_news
    from gridlens.intelligence.change_detection import (
        material_state,
        record_material_diff,
        seed_material_state,
    )

    permit_definition = next(
        row for row in load_registry() if row["id"] == "austin-building-permits"
    )
    with factory.begin() as session:
        permit_source = Source(
            id=permit_definition["id"],
            publisher=permit_definition["publisher"],
            endpoint=permit_definition["endpoint"],
            family=permit_definition["family"],
            geography="US",
            industries=["industrial"],
            retrieval_method=permit_definition["retrieval_method"],
            health={},
        )
        session.add(permit_source)
        session.flush()
        # This exercises the supported assessment branch with an actual
        # admitted official source; publisher-RSS itself remains context-only.
        news_record = _project_record(
            "Atlas Mesa data center campus capacity is 200 MW, but Atlas Mesa data center "
            "construction requires about 42 MW. Power supply for Atlas Mesa data center "
            "construction is delayed. Site address: 100 Main Street, Austin, TX."
        )
        observation = Observation(
            source_id=permit_source.id,
            external_id="supported-official-claim",
            title=news_record["title"],
            abstract=news_record["abstract"],
            published_at=date.fromisoformat(news_record["publication_date"]),
            url=news_record["html_url"],
            content_hash=hashlib.sha256(
                f"{news_record['title']}|{news_record['abstract']}".encode()
            ).hexdigest(),
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=news_record["source_hash"],
            title=news_record["title"],
            abstract=news_record["abstract"],
            url=news_record["html_url"],
            published_at=observation.published_at,
        )
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                status="pending",
                attempts=0,
            )
        )
        session.add(evidence)
        session.flush()
        assert admit_standalone(
            source_id=permit_source.id,
            family=permit_source.family,
            retrieval_method=permit_source.retrieval_method,
            accepted=True,
            activity="facility-expansion",
            title=evidence.title,
            abstract=evidence.abstract,
            dated=True,
            citation_url=evidence.url,
            identified_project=True,
        ).admitted
        assert assess_retained_news(session, observation, evidence) is True
        project = session.scalar(select(Project))
        need = session.scalar(select(PowerNeed))
        assert project is not None and need is not None
        assert (need.tier, need.required_mw, need.supply) == (
            "Prospect",
            "about 42 MW",
            "Reported constraint",
        )
        from gridlens.intelligence.project_state import project_state

        projected_need = project_state(session, project.id)["state"]["power_need"]["value"][0]
        assert {
            name: projected_need[name]["status"] for name in ("activity", "tier", "mw", "supply")
        } == {
            "activity": "SUPPORTED",
            "tier": "SUPPORTED",
            "mw": "SUPPORTED",
            "supply": "SUPPORTED",
        }
        material = session.scalar(
            select(ChangeEvent).where(
                ChangeEvent.project_id == project.id,
                ChangeEvent.field_name == "power_need",
                ChangeEvent.evidence_id == evidence.id,
            )
        )
        assert material is not None
        assert material.prior_state == {"value": []}
        power_state = material.new_state["value"][0]
        assert (power_state["tier"], power_state["required_mw"], power_state["supply"]) == (
            "Prospect",
            "about 42 MW",
            "Reported constraint",
        )
        assert material.new_state != material.prior_state
        event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert assess_retained_news(session, observation, evidence) is False
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count

        # A second immutable version of the same admitted official record must
        # attribute an existing need's tier, load, and supply transition to
        # that exact version.
        revised = _project_record(
            news_record["abstract"].replace("about 42 MW", "about 58 MW"),
            news_record["title"],
        )
        observation.title = revised["title"]
        observation.abstract = revised["abstract"]
        observation.content_hash = revised["source_hash"]
        observation.published_at = date.fromisoformat(revised["publication_date"])
        revised_evidence = Evidence(
            observation_id=observation.id,
            content_hash=revised["source_hash"],
            title=revised["title"],
            abstract=revised["abstract"],
            url=revised["html_url"],
            published_at=observation.published_at,
        )
        session.add(revised_evidence)
        session.flush()
        assert assess_retained_news(session, observation, revised_evidence) is True
        session.refresh(need)
        assert (need.tier, need.required_mw, need.supply) == (
            "Prospect",
            "about 58 MW",
            "Reported constraint",
        )
        revised_event = session.scalar(
            select(ChangeEvent).where(
                ChangeEvent.project_id == project.id,
                ChangeEvent.field_name == "power_need",
                ChangeEvent.evidence_id == revised_evidence.id,
            )
        )
        assert revised_event is not None
        prior_power = revised_event.prior_state["value"][0]
        current_power = revised_event.new_state["value"][0]
        assert (prior_power["tier"], prior_power["required_mw"], prior_power["supply"]) == (
            "Prospect",
            "about 42 MW",
            "Reported constraint",
        )
        assert (current_power["tier"], current_power["required_mw"], current_power["supply"]) == (
            "Prospect",
            "about 58 MW",
            "Reported constraint",
        )
        assert revised_event.new_state == {
            "value": material_state(session, project.id)["power_need"]
        }
        revised_event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert assess_retained_news(session, observation, revised_evidence) is False
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == revised_event_count

        signal = _project_record(
            "Site address: 100 Main Street, Austin, TX. Atlas Mesa data center "
            "construction is planned.",
            news_record["title"],
        )
        observation.title = signal["title"]
        observation.abstract = signal["abstract"]
        observation.content_hash = signal["source_hash"]
        observation.published_at = date.fromisoformat(signal["publication_date"])
        signal_evidence = Evidence(
            observation_id=observation.id,
            content_hash=signal["source_hash"],
            title=signal["title"],
            abstract=signal["abstract"],
            url=signal["html_url"],
            published_at=observation.published_at,
        )
        session.add(signal_evidence)
        session.flush()
        assert assess_retained_news(session, observation, signal_evidence) is True
        session.refresh(need)
        assert (need.tier, need.required_mw, need.supply) == ("Signal", None, "Unknown")
        signal_event = session.scalar(
            select(ChangeEvent).where(
                ChangeEvent.project_id == project.id,
                ChangeEvent.field_name == "power_need",
                ChangeEvent.evidence_id == signal_evidence.id,
            )
        )
        assert signal_event is not None
        assert signal_event.prior_state["value"][0] == {
            **signal_event.prior_state["value"][0],
            "tier": "Prospect",
            "required_mw": "about 58 MW",
            "supply": "Reported constraint",
        }
        assert signal_event.new_state == {
            "value": material_state(session, project.id)["power_need"]
        }
        latest_event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert assess_retained_news(session, observation, signal_evidence) is False
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == latest_event_count

        unrelated_observation = Observation(
            source_id=permit_source.id,
            external_id="unrelated-permit",
            title="Unrelated permit",
            abstract="A different project.",
            published_at=date(2026, 9, 30),
            url="https://example.test/permit/unrelated",
            content_hash="unrelated-semantic-hash",
        )
        session.add(unrelated_observation)
        session.flush()
        unrelated_evidence = Evidence(
            observation_id=unrelated_observation.id,
            content_hash="unrelated-evidence-hash",
            title=unrelated_observation.title,
            abstract=unrelated_observation.abstract,
            url=unrelated_observation.url,
            published_at=unrelated_observation.published_at,
        )
        session.add(unrelated_evidence)
        session.flush()
        baseline = seed_material_state(session, project)
        assert record_material_diff(session, project, unrelated_evidence, baseline) == []
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == latest_event_count


@pytest.mark.parametrize("check_initial_binding", [True, False])
def test_official_same_hash_reassignment_clears_former_project_support_and_keeps_history(
    db, check_initial_binding
):
    """An evaluator correction moves one immutable official citation from A to B."""
    from gridlens.domain.news_interpretation import assess_news
    from gridlens.domain.signal_admission import admit_standalone
    from gridlens.ingestion.registry import load_registry
    from gridlens.ingestion.service import _news_identity_key, assess_retained_news
    from gridlens.intelligence.buying_chain import buying_chain_view
    from gridlens.intelligence.change_detection import record_material_diff, seed_material_state
    from gridlens.intelligence.lifecycle_service import apply_lifecycle_observation
    from gridlens.intelligence.project_state import project_state
    from gridlens.persistence.models import (
        BuyingChainClaim,
        BuyingChainEvidence,
        BuyingChainRun,
        LifecycleEvent,
        ProjectLifecycle,
    )

    _, factory, _ = db
    definition = next(row for row in load_registry() if row["id"] == "austin-building-permits")
    summary = (
        "Atlas Mesa data center construction requires about 42 MW. Power supply for "
        "Atlas Mesa data center construction is delayed. Site address: 100 Main Street, "
        "Austin, TX. Acme Builders is the general contractor for Atlas Mesa data center."
    )
    record = _project_record(summary)
    claim = assess_news(record["title"], record["abstract"]).as_dict()
    assert claim["decision"] == "accepted"
    target_key = _news_identity_key(
        record["title"], record["abstract"], definition["id"], "same-hash-correction", claim
    )
    with factory.begin() as session:
        source = Source(
            id=definition["id"],
            publisher=definition["publisher"],
            endpoint=definition["endpoint"],
            family=definition["family"],
            geography="US",
            industries=["industrial"],
            retrieval_method=definition["retrieval_method"],
            health={},
        )
        session.add(source)
        session.flush()
        former = Project(
            identity_key="historical-atlas-binding",
            name="Historical Atlas assignment",
            location="Dallas, TX",
            source_id=source.id,
            external_id="historical-atlas",
            identity_facts={"site": "Dallas, TX"},
        )
        selected = Project(
            identity_key=target_key,
            name=claim["subject"],
            location=claim["location"],
            source_id=source.id,
            external_id="selected-atlas",
            identity_facts={"site": claim["location"], "project_aliases": [claim["subject"]]},
        )
        session.add_all([former, selected])
        session.flush()
        observation = Observation(
            source_id=source.id,
            external_id="same-hash-correction",
            title=record["title"],
            abstract=record["abstract"],
            published_at=date.fromisoformat(record["publication_date"]),
            url=record["html_url"],
            content_hash=record["source_hash"],
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=record["source_hash"],
            title=record["title"],
            abstract=record["abstract"],
            url=record["html_url"],
            published_at=observation.published_at,
        )
        session.add(evidence)
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                evaluator_version="earlier-evaluator",
                status="accepted",
                attempts=1,
                assessment={
                    **claim,
                    "subject": "Historical Atlas assignment",
                    "location": "Dallas, TX",
                    "project_identity_key": former.identity_key,
                    "power_activity": "construction",
                    "semantic_hash": observation.content_hash,
                    "evidence_hash": evidence.content_hash,
                    "admission_status": "admitted",
                },
            )
        )
        session.flush()
        admission = admit_standalone(
            source_id=source.id,
            family=source.family,
            retrieval_method=source.retrieval_method,
            accepted=True,
            activity="construction",
            title=evidence.title,
            abstract=evidence.abstract,
            dated=True,
            citation_url=evidence.url,
            identified_project=True,
        )
        assert admission.admitted
        old_need = PowerNeed(
            project_id=former.id,
            activity_key="construction",
            tier="Signal",
            rationale="Historical accepted assignment.",
            supply="Unknown",
            active=True,
            admission_basis=admission.as_basis(source.id, evidence.content_hash),
        )
        session.add(old_need)
        session.flush()
        session.add(NeedObservation(need_id=old_need.id, observation_id=observation.id))
        apply_lifecycle_observation(session, former, observation, evidence)
        assert session.get(ProjectLifecycle, former.id) is not None

        quote = "Acme Builders is the general contractor for Atlas Mesa data center."
        chain_claim_ids = {}
        for project in (former, selected):
            chain_evidence = BuyingChainEvidence(
                project_id=project.id,
                retained_evidence_id=evidence.id,
                url=evidence.url,
                title=evidence.title,
                excerpt=quote,
                content_hash=evidence.content_hash,
                extraction_location="official filing title and abstract",
                published_at=evidence.published_at,
                observed_at=evidence.observed_at,
                last_seen_at=evidence.observed_at,
                project_match_reason="Historical interpretation or corrected project binding.",
            )
            session.add(chain_evidence)
            session.flush()
            chain_claim = BuyingChainClaim(
                project_id=project.id,
                entity_key="acme-builders",
                fingerprint=f"acme-builders-{project.id}",
                policy_version="test",
                organization="Acme Builders",
                person_name=None,
                title=None,
                category="general_contractor",
                organization_relationship="DIRECT",
                person_organization_relationship="UNKNOWN",
                person_project_relationship="UNKNOWN",
                evidence_strength="High",
                reason="Official retained citation.",
                citations=[{
                    "evidence_id": str(chain_evidence.id),
                    "url": evidence.url,
                    "quote": quote,
                    "supports": "organization_category",
                }],
                public_contacts=[],
                observed_at=evidence.observed_at,
            )
            session.add(chain_claim)
            session.flush()
            chain_claim_ids[project.id] = chain_claim.id
            session.add(
                BuyingChainRun(
                    project_id=project.id,
                    input_hash=f"same-hash-{project.id}",
                    evidence_ids=[str(chain_evidence.id)],
                    claim_ids=[str(chain_claim.id)],
                    policy_version="test",
                    status="complete",
                    documents_checked=1,
                    candidates_added=1,
                    unresolved=[],
                )
            )
        session.flush()
        assert project_state(session, former.id)["state"]["lifecycle"]["status"] == "SUPPORTED"
        assert buying_chain_view(session, former.id)["candidates"]
        if check_initial_binding:
            assert buying_chain_view(session, selected.id)["candidates"] == []
        before_evidence = (evidence.id, evidence.content_hash, evidence.title, evidence.abstract)
        assert assess_retained_news(session, observation, evidence) is True
        session.flush()

        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert (
            evidence.id,
            evidence.content_hash,
            evidence.title,
            evidence.abstract,
        ) == before_evidence
        assert session.get(ProjectLifecycle, former.id) is None
        assert project_state(session, former.id)["state"]["lifecycle"]["status"] == "UNKNOWN"
        assert session.scalar(
            select(func.count())
            .select_from(LifecycleEvent)
            .where(LifecycleEvent.project_id == former.id)
        ) >= 1  # The historical event remains retained.
        assert buying_chain_view(session, former.id)["candidates"] == []
        assert any(
            row["id"] == chain_claim_ids[former.id]
            for row in buying_chain_view(session, former.id, history=True)["candidates"]
        )
        assert any(
            row["id"] == chain_claim_ids[selected.id]
            for row in buying_chain_view(session, selected.id)["candidates"]
        )
        assert project_state(session, selected.id)["state"]["lifecycle"]["status"] == "SUPPORTED"
        assert session.scalar(
            select(func.count()).select_from(ChangeEvent).where(
                ChangeEvent.project_id == former.id,
                ChangeEvent.evidence_id == evidence.id,
                ChangeEvent.field_name.in_(["phase", "contractor", "buyer"]),
            )
        ) >= 3
        selected_fields = set(
            session.scalars(
                select(ChangeEvent.field_name).where(
                    ChangeEvent.project_id == selected.id,
                    ChangeEvent.evidence_id == evidence.id,
                )
            ).all()
        )
        assert {"phase", "contractor", "buyer"} <= selected_fields
        event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert assess_retained_news(session, observation, evidence) is False
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count
        unrelated = Observation(
            source_id=source.id,
            external_id="unrelated-after-reassignment",
            title="Unrelated official record",
            abstract="Another site.",
            url="https://example.test/permit/unrelated-reassignment",
            published_at=date(2026, 9, 30),
            content_hash="unrelated-after-reassignment",
        )
        session.add(unrelated)
        session.flush()
        unrelated_evidence = Evidence(
            observation_id=unrelated.id,
            content_hash=unrelated.content_hash,
            title=unrelated.title,
            abstract=unrelated.abstract,
            url=unrelated.url,
            published_at=unrelated.published_at,
        )
        session.add(unrelated_evidence)
        session.flush()
        for project in (former, selected):
            baseline = seed_material_state(session, project)
            assert record_material_diff(session, project, unrelated_evidence, baseline) == []
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count


@pytest.mark.parametrize("prospect_first", [True, False])
def test_news_only_signal_and_prospect_claims_never_create_a_need(db, monkeypatch, prospect_first):
    _, factory, _ = db
    prospect_job = _rss_source_job(factory, "atlas-prospect-news", "Atlas Prospect News")
    signal_job = _rss_source_job(factory, "atlas-signal-news", "Atlas Signal News")
    import gridlens.ingestion.service as service

    title = "Atlas begins construction at Atlas Mesa data center in Texas"
    site = "Site address: 100 Main Street, Austin, TX."
    prospect = _project_record(
        "Atlas Mesa data center campus capacity is 200 MW, but Atlas Mesa data center "
        "construction requires about 42 MW. Power supply for Atlas Mesa data center "
        f"construction is delayed. {site}",
        title,
    )
    signal = _project_record(f"{site} Atlas Mesa data center construction is planned.", title)
    rows = {"atlas-prospect-news": prospect, "atlas-signal-news": signal}
    jobs = {"atlas-prospect-news": prospect_job, "atlas-signal-news": signal_job}
    monkeypatch.setattr(
        service, "retrieve_source", lambda definition, _client: [rows[definition["id"]]]
    )

    def ingest(source_id):
        with factory() as session:
            return service.process_job(
                session,
                jobs[source_id],
                "test",
                1,
                {"id": source_id, "retrieval_method": "publisher-rss"},
            )

    order = (
        ["atlas-prospect-news", "atlas-signal-news"]
        if prospect_first
        else ["atlas-signal-news", "atlas-prospect-news"]
    )
    for source_id in order:
        ingest(source_id)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 0
        signal_assessment = session.scalar(
            select(Interpretation.assessment)
            .join(Observation)
            .where(Observation.source_id == "atlas-signal-news")
        )
        assert signal_assessment and signal_assessment["tier"] == "Signal"
        assert signal_assessment["admission_status"] == "supplement_unmatched"
        prospect_row = session.scalar(
            select(Observation).where(Observation.source_id == "atlas-prospect-news")
        )
        signal_row = session.scalar(
            select(Observation).where(Observation.source_id == "atlas-signal-news")
        )
        assert prospect_row and signal_row
        assert prospect_row and signal_row

    rows["atlas-prospect-news"] = _project_record(
        f"Atlas canceled construction at Atlas Mesa data center. {site}",
        title.replace("begins", "canceled"),
    )
    assert ingest("atlas-prospect-news")["changed"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0


def test_news_only_duplicate_correction_and_replay_preserve_evidence_without_needs(db, monkeypatch):
    _, factory, _ = db
    dcd_job = _rss_source_job(factory, "dcd-news", "Data Center Dynamics")
    utility_job = _rss_source_job(factory, "utility-dive-news", "Utility Dive")
    import gridlens.ingestion.service as service

    first = _project_record()
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [first])
    with factory() as session:
        initial = service.process_job(
            session, dcd_job, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    assert initial["signals"] == 0
    with factory() as session:
        replay = service.process_job(
            session, dcd_job, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    assert replay["signals"] == 0

    # Exact title/summary duplicate from another configured feed links to the same event.
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [first])
    with factory() as session:
        service.process_job(
            session,
            utility_job,
            "test",
            1,
            {"id": "utility-dive-news", "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0

    # One source correction preserves the need while the second cited source remains current.
    corrected = _project_record(
        "Atlas canceled construction at the Atlas Mesa data center in Texas."
    )
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [corrected])
    with factory() as session:
        service.process_job(
            session, dcd_job, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need is None
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        interpretation = session.scalar(
            select(Interpretation).join(Observation).where(Observation.source_id == "dcd-news")
        )
        assert interpretation and interpretation.status == "rejected"
        assert interpretation.assessment and interpretation.assessment["decision"] == "rejected"
        assert len(interpretation.assessment["previous_decisions"]) == 1
        event_count = session.scalar(select(func.count()).select_from(ChangeEvent))

    # The need closes only after its final currently accepted source is withdrawn.
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [corrected])
    with factory() as session:
        service.process_job(
            session,
            utility_job,
            "test",
            1,
            {"id": "utility-dive-news", "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need is None
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 4
        event_count = session.scalar(select(func.count()).select_from(ChangeEvent))

    with factory() as session:
        service.process_job(
            session, dcd_job, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == event_count
        assert session.scalar(select(func.count()).select_from(Evidence)) == 4


@pytest.mark.parametrize(
    ("news_first", "news_phase"),
    [
        (False, None),
        (True, None),
        (False, "Phase II"),
        (False, "Phases 1 and 2"),
        (False, "Phase 1–2"),
        (False, "Phase 1 and 2"),
    ],
)
def test_current_rss_supplement_matches_permit_by_explicit_project_and_site(
    db, monkeypatch, news_first, news_phase
):
    _, factory, _ = db
    from gridlens.ingestion.registry import load_registry
    from gridlens.persistence.models import ProjectMatchDecision, SignalDecision

    permit_source_id = "austin-building-permits"
    news_source_id = "northstar-news"
    permit_definition = next(row for row in load_registry() if row["id"] == permit_source_id)
    with factory.begin() as session:
        for source_id, publisher, endpoint, method, family in (
            (
                permit_source_id,
                permit_definition["publisher"],
                permit_definition["endpoint"],
                permit_definition["retrieval_method"],
                permit_definition["family"],
            ),
            (
                news_source_id,
                "Northstar News",
                "https://example.test/feed",
                "publisher-rss",
                "news",
            ),
        ):
            session.add(
                Source(
                    id=source_id,
                    publisher=publisher,
                    endpoint=endpoint,
                    family=family,
                    geography="US",
                    industries=["industrial"],
                    retrieval_method=method,
                    health={},
                )
            )
            session.flush()
            job = Job(
                source_id=source_id,
                status="running",
                lease_owner="test",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            if source_id == permit_source_id:
                permit_job_id = job.id
            else:
                news_job_id = job.id

    permit = {
        "document_number": "PX-1",
        "title": "Austin building permit PX-1 — Building Permit",
        "abstract": (
            "address: 100 Main Street, Austin, TX\n"
            "project: Northstar Mesa data center\n"
            "description: Construction of the Northstar Mesa data center at 100 Main Street, "
            "Austin, TX\n"
            "status: Active"
        ),
        "publication_date": "2026-09-20",
        "event_date": "2026-09-20",
        "html_url": "https://example.test/permit/PX-1",
        "permit": {
            "row_id": "PX-1",
            "description": (
                "Construction of the Northstar Mesa data center at 100 Main Street, Austin, TX"
            ),
            "status": "Active",
            "address": "100 Main Street",
            "city": "Austin",
            "state": "TX",
            "project": "Northstar Mesa data center",
            "source_fields": {"address": "original_address1", "project": "project_id"},
        },
    }
    news = {
        "document_number": "N-1",
        "title": (
            "Northstar begins construction at the Northstar Mesa data center in Austin, "
            f"Texas {news_phase or ''}"
        ),
        "abstract": "Site address: 100 Main Street, Austin, TX.",
        "publication_date": "2026-09-21",
        "html_url": "https://example.test/news/N-1",
    }
    records = {permit_source_id: [permit], news_source_id: [news]}
    import gridlens.ingestion.service as service

    monkeypatch.setattr(
        service, "retrieve_source", lambda definition, _client: records[definition["id"]]
    )

    def ingest(source_id):
        with factory() as session:
            return service.process_job(
                session,
                permit_job_id if source_id == permit_source_id else news_job_id,
                "test",
                1,
                {**permit_definition, "id": permit_source_id}
                if source_id == permit_source_id
                else {"id": news_source_id, "retrieval_method": "publisher-rss"},
            )

    if news_first:
        assert ingest(news_source_id)["signals"] == 0
        assert ingest(permit_source_id)["permit_accepted"] == 1
        news_counts = ingest(news_source_id)  # Replays the unchanged item after the permit arrives.
    else:
        assert ingest(permit_source_id)["permit_accepted"] == 1
        news_counts = ingest(news_source_id)
    assert news_counts["signals"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == (
            1 if news_phase else 2
        )
        project = session.scalar(select(Project))
        need = session.scalar(select(PowerNeed))
        assert project and project.identity_facts["project_aliases"] == [
            "Northstar Mesa data center"
        ]
        assert need and need.activity_key == "facility-expansion" and need.tier == "Signal"
        assert need.required_mw is None and need.supply == "Unknown"
        assert need.admission_basis["origin"] == "Official permit"
        news_observation = session.scalar(
            select(Observation).where(Observation.source_id == news_source_id)
        )
        assert news_observation is not None
        decision = session.scalar(
            select(ProjectMatchDecision).where(
                ProjectMatchDecision.observation_id == news_observation.id,
                ProjectMatchDecision.candidate_project_id == project.id,
            )
        )
        if news_phase:
            unknown = session.scalar(
                select(Interpretation).where(Interpretation.observation_id == news_observation.id)
            )
            assert decision is None
            assert unknown.assessment["admission_status"] == "supplement_unknown"
            assert "UNKNOWN" in unknown.assessment["admission_reason"]
        else:
            assert decision and decision.decision == "matched", (
                decision.reason if decision else None
            )
        display_decision = session.scalar(
            select(SignalDecision).where(
                SignalDecision.observation_id == news_observation.id,
                SignalDecision.content_hash
                == session.scalar(
                    select(Evidence.content_hash).where(
                        Evidence.observation_id == news_observation.id
                    )
                ),
            )
        )
        assert display_decision is None
        assessment = session.scalar(
            select(Interpretation.assessment)
            .join(Observation)
            .where(Observation.source_id == news_source_id)
        )
        assert assessment and assessment["admission_status"] == (
            "supplement_unknown" if news_phase else "supplemental"
        )
        if not news_phase:
            assert "physical address" in decision.reason
            assert "project name/alias" in decision.reason
            assert decision.identity_facts["site"] == "100 Main Street, Austin, TX"
        citations = session.scalars(
            select(Observation.source_id)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .where(NeedObservation.need_id == need.id)
        ).all()
        assert set(citations) == (
            {permit_source_id} if news_phase else {permit_source_id, news_source_id}
        )

    news_correction = {
        **news,
        "title": "Another project begins construction at a data center in Austin, Texas",
        "abstract": "Site address: 200 Other Street, Austin, TX.",
    }
    records[news_source_id] = [news_correction]
    with factory() as session:
        service.process_job(
            session,
            news_job_id,
            "test",
            1,
            {"id": news_source_id, "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need and need.active
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == (
            1 if news_phase else 2
        )
        current_news = session.scalar(
            select(Interpretation).join(Observation).where(Observation.source_id == news_source_id)
        )
        assert current_news.assessment["admission_status"] != "supplemental"
        assert current_news.assessment["subject"] != "Northstar Mesa data center"
    if not news_phase:
        import importlib

        api_module = importlib.import_module("gridlens.api.app")
        monkeypatch.setattr(api_module, "SessionLocal", factory)
        cards = api_module.opportunities(tier="Signal")
        assert len(cards) == 1
        news_card_evidence = [
            item for item in cards[0]["evidence"] if item["source_id"] == news_source_id
        ]
        assert news_card_evidence
        assert all(item["assessment_current"] is False for item in news_card_evidence)
        assert "Another project" not in cards[0]["rationale"]

    permit["abstract"] = (
        "address: 100 Main Street, Austin, TX\nproject: Northstar Mesa data center\n"
        "description: Routine maintenance at an existing office; no construction work\n"
        "status: Active"
    )
    permit["permit"]["description"] = (
        "Routine maintenance at an existing office; no construction work"
    )
    records[permit_source_id] = [permit]
    with factory() as session:
        permit_counts = service.process_job(
            session,
            permit_job_id,
            "test",
            1,
            {**permit_definition, "id": permit_source_id},
        )
    assert permit_counts["permit_rejected"] == 1
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need and not need.active
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == (
            1 if news_phase else 2
        )
        assert session.scalar(select(func.count()).select_from(Evidence)) == 4
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        stable_event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
    with factory() as session:
        service.process_job(
            session,
            news_job_id,
            "test",
            1,
            {"id": news_source_id, "retrieval_method": "publisher-rss"},
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == stable_event_count
        assert session.scalar(select(func.count()).select_from(Evidence)) == 4


def test_phase_numbered_same_building_permits_consolidate_but_distinct_buildings_do_not(
    db, monkeypatch
):
    _, factory, _ = db
    import gridlens.ingestion.service as service
    from gridlens.ingestion.registry import load_registry

    source_id = "austin-building-permits"
    definition = next(row for row in load_registry() if row["id"] == source_id)
    with factory.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography="Austin, TX",
                industries=["industrial"],
                retrieval_method=definition["retrieval_method"],
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=source_id,
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    def permit(number: int, building: str) -> dict:
        address = f"1300 E ANDERSON LN SVRD WB BLDG {building}"
        description = (
            f"ePlan: Commercial Expedited Review - Phase {number}: Interior Remodel to "
            "Existing Manufacturing Facility (20000 SF)."
        )
        return {
            "document_number": f"PH-{building}-{number}",
            "title": f"Austin building permit PH-{building}-{number} — Building Permit",
            "abstract": (
                f"address: {address}, Austin, TX\ndescription: {description}\nstatus: Active"
            ),
            "publication_date": "2026-09-20",
            "event_date": "2026-09-20",
            "html_url": f"https://example.test/permit/PH-{building}-{number}",
            "permit": {
                "row_id": f"PH-{building}-{number}",
                "description": description,
                "status": "Active",
                "address": address,
                "city": "Austin",
                "state": "TX",
                "project": None,
                "source_fields": {"address": "original_address1", "project": "project_id"},
            },
        }

    records = [permit(2, "B"), permit(3, "B"), permit(4, "B"), permit(2, "A")]
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: records)
    with factory() as session:
        counts = service.process_job(session, job_id, "test", 1, {**definition, "id": source_id})
    assert counts["permit_accepted"] == 4
    with factory() as session:
        projects = session.scalars(select(Project)).all()
        assert len(projects) == 2
        building_b = next(
            project
            for project in projects
            if project.identity_facts.get("facility_source_address", "").endswith("BLDG B")
        )
        building_a = next(
            project
            for project in projects
            if project.identity_facts.get("facility_source_address", "").endswith("BLDG A")
        )
        assert building_a.id != building_b.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(NeedObservation)
                .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
                .where(PowerNeed.project_id == building_b.id)
            )
            == 3
        )

    def need_snapshot():
        with factory() as session:
            return {
                str(need.id): {
                    column.name: getattr(need, column.name)
                    for column in PowerNeed.__table__.columns
                }
                for need in session.scalars(select(PowerNeed))
            }

    before = need_snapshot()
    # Three unchanged permits support one need. Replaying them must not rotate
    # its valid admission citation or make the opportunity appear freshly updated.
    with factory() as session:
        assert service.process_job(session, job_id, "test", 1, definition)["unchanged"] == 4
    assert need_snapshot() == before
    records.reverse()
    with factory() as session:
        assert service.process_job(session, job_id, "test", 1, definition)["unchanged"] == 4
    assert need_snapshot() == before

    # Retaining a valid basis must still allow an outdated policy to be repaired.
    with factory.begin() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.project_id == building_b.id))
        assert need is not None
        need.admission_basis = {**need.admission_basis, "policy_version": "retired-fixture-policy"}
    with factory() as session:
        service.process_job(session, job_id, "test", 1, definition)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.project_id == building_b.id))
        assert need is not None
        assert need.admission_basis["policy_version"] == "signal-admission-v1"


def test_multiple_labeled_rss_sites_keep_record_separate_with_persisted_ambiguity(db, monkeypatch):
    _, factory, _ = db
    from gridlens.ingestion.registry import load_registry
    from gridlens.intelligence.project_identity import labeled_site
    from gridlens.persistence.models import ProjectMatchDecision

    permit_source_id = "austin-building-permits"
    news_source_id = "northstar-news"
    permit_definition = next(row for row in load_registry() if row["id"] == permit_source_id)
    with factory.begin() as session:
        for source_id, publisher, endpoint, method, family in (
            (
                permit_source_id,
                permit_definition["publisher"],
                permit_definition["endpoint"],
                permit_definition["retrieval_method"],
                permit_definition["family"],
            ),
            (
                news_source_id,
                "Northstar News",
                "https://example.test/feed",
                "publisher-rss",
                "news",
            ),
        ):
            session.add(
                Source(
                    id=source_id,
                    publisher=publisher,
                    endpoint=endpoint,
                    family=family,
                    geography="US",
                    industries=["industrial"],
                    retrieval_method=method,
                    health={},
                )
            )
            session.flush()
            job = Job(
                source_id=source_id,
                status="running",
                lease_owner="test",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            if source_id == permit_source_id:
                permit_job_id = job.id
            else:
                news_job_id = job.id

    permit = {
        "document_number": "PX-1",
        "title": "Austin building permit PX-1 — Building Permit",
        "abstract": (
            "address: 100 Main Street, Austin, TX\n"
            "project: Northstar Mesa data center\n"
            "description: Construction of the Northstar Mesa data center at 100 Main Street, "
            "Austin, TX\nstatus: Active"
        ),
        "publication_date": "2026-09-20",
        "event_date": "2026-09-20",
        "html_url": "https://example.test/permit/PX-1",
        "permit": {
            "row_id": "PX-1",
            "description": (
                "Construction of the Northstar Mesa data center at 100 Main Street, Austin, TX"
            ),
            "status": "Active",
            "address": "100 Main Street",
            "city": "Austin",
            "state": "TX",
            "project": "Northstar Mesa data center",
            "source_fields": {"address": "original_address1", "project": "project_id"},
        },
    }
    news = {
        "document_number": "N-2",
        "title": "Northstar begins construction at the Northstar Mesa data center in Austin, Texas",
        "abstract": (
            "Site address: 100 Main Street, Austin, TX. Site address: 200 Elm Street, Austin, TX."
        ),
        "publication_date": "2026-09-21",
        "html_url": "https://example.test/news/N-2",
    }
    assert (
        labeled_site(
            "Site address: 100 Main Street, Austin, TX. Site address: 100 Main Street, Austin, TX."
        )
        == "100 Main Street, Austin, TX"
    )
    assert labeled_site(news["abstract"]) is None
    records = {permit_source_id: [permit], news_source_id: [news]}
    import gridlens.ingestion.service as service

    monkeypatch.setattr(
        service, "retrieve_source", lambda definition, _client: records[definition["id"]]
    )
    with factory() as session:
        service.process_job(
            session,
            permit_job_id,
            "test",
            1,
            {**permit_definition, "id": permit_source_id},
        )
    with factory() as session:
        counts = service.process_job(
            session,
            news_job_id,
            "test",
            1,
            {"id": news_source_id, "retrieval_method": "publisher-rss"},
        )
    assert counts["signals"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        observation = session.scalar(
            select(Observation).where(Observation.source_id == news_source_id)
        )
        assert observation is not None
        decision = session.scalar(
            select(ProjectMatchDecision).where(
                ProjectMatchDecision.observation_id == observation.id,
            )
        )
        assert decision and decision.decision == "separate"
        assert "UNKNOWN" in decision.reason
        assert decision.identity_facts["site_candidates"] == [
            "100 Main Street, Austin, TX",
            "200 Elm Street, Austin, TX",
        ]


def test_rss_fence_loss_after_durable_evidence_is_retryable(db, monkeypatch):
    _, factory, _ = db
    job_id = _rss_source_job(factory, "dcd-news", "Data Center Dynamics")
    import gridlens.ingestion.service as service

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_project_record()])
    original_fence = service.assert_fence
    calls = 0

    def lose_after_evidence(session, current_job_id, worker_id, fence):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("Worker lease fence lost")
        return original_fence(session, current_job_id, worker_id, fence)

    monkeypatch.setattr(service, "assert_fence", lose_after_evidence)
    with factory() as session, pytest.raises(RuntimeError, match="fence"):
        service.process_job(
            session, job_id, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        pending = session.scalar(select(Interpretation))
        assert pending and pending.status == "pending"

    monkeypatch.setattr(service, "assert_fence", original_fence)
    with factory() as session:
        service.process_job(
            session, job_id, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(Interpretation)).status == "accepted"


def test_apply_reports_interpretation_failure_and_retries(db, monkeypatch, tmp_path):
    _, factory, _ = db
    job_id = _rss_source_job(factory, "dcd-news", "Data Center Dynamics")
    import gridlens.ingestion.service as service

    script_path = Path(__file__).parents[3] / "scripts" / "reinterpret_news.py"
    spec = importlib.util.spec_from_file_location("reinterpret_news", script_path)
    assert spec and spec.loader
    reinterpret_news = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reinterpret_news)

    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [_project_record()])
    with factory() as session:
        service.process_job(
            session, job_id, "test", 1, {"id": "dcd-news", "retrieval_method": "publisher-rss"}
        )
    with factory.begin() as session:
        interpretation = session.scalar(select(Interpretation))
        interpretation.evaluator_version = "old-evaluator"
    original_assess = service.assess_news
    monkeypatch.setattr(
        service, "assess_news", lambda *_args: (_ for _ in ()).throw(RuntimeError())
    )
    monkeypatch.setattr("gridlens.persistence.database.SessionLocal", factory)
    output = tmp_path / "apply.json"
    monkeypatch.setattr(
        sys, "argv", ["reinterpret_news.py", "--apply", "--limit", "1", "--output", str(output)]
    )
    with pytest.raises(SystemExit) as failed:
        reinterpret_news.main()
    assert failed.value.code == 1
    failure_report = json.loads(output.read_text(encoding="utf-8"))
    assert failure_report["failed_or_pending"] == 1
    assert failure_report["decisions"][0]["status"] == "failed"
    assert failure_report["decisions"][0]["assessment"]["decision"] == "accepted"
    with factory() as session:
        interpretation = session.scalar(select(Interpretation))
        assert interpretation and interpretation.status == "failed"
        assert interpretation.assessment["decision"] == "accepted"

    monkeypatch.setattr(service, "assess_news", original_assess)
    reinterpret_news.main()
    retry_report = json.loads(output.read_text(encoding="utf-8"))
    assert retry_report["failed_or_pending"] == 0
    assert retry_report["decisions"][0]["status"] == "accepted"


def test_authenticated_inbox_filters_and_paginates_retained_versions(db, monkeypatch):
    _, factory, _ = db
    monkeypatch.setattr("gridlens.api.app.SessionLocal", factory)
    with factory.begin() as session:
        session.add(
            Source(
                id="nc-commerce",
                publisher="North Carolina Department of Commerce",
                endpoint="https://www.commerce.nc.gov/news/press-releases",
                family="economic-development-publication",
                geography="North Carolina",
                industries=["manufacturing"],
                retrieval_method="nc-commerce-html",
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        observation = Observation(
            source_id="mjbizdaily-news",
            external_id="https://mjbizdaily.com/news/cultivation-facility/",
            title="A company announces a cultivation facility",
            abstract="Licensing and construction update",
            published_at=datetime(2026, 9, 25).date(),
            url="https://mjbizdaily.com/news/cultivation-facility/",
            content_hash="a" * 64,
        )
        session.add(observation)
        session.flush()
        session.add_all(
            [
                Evidence(
                    observation_id=observation.id,
                    content_hash=char * 64,
                    title=observation.title,
                    abstract=observation.abstract,
                    url=observation.url,
                    published_at=observation.published_at,
                    extraction_location="RSS item title and description/summary",
                )
                for char in ("a", "b")
            ]
        )
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash="a" * 64,
                status="collection_only",
            )
        )
        nc_observation = Observation(
            source_id="nc-commerce",
            external_id="NC-TEST-1",
            title="Synthetic manufacturing announcement",
            abstract="A manufacturing site expansion.",
            published_at=datetime(2026, 9, 20).date(),
            url="https://www.commerce.nc.gov/news/press-releases/synthetic",
            content_hash="c" * 64,
        )
        session.add(nc_observation)
        session.flush()
        session.add(
            Evidence(
                observation_id=nc_observation.id,
                content_hash="c" * 64,
                title=nc_observation.title,
                abstract=nc_observation.abstract,
                url=nc_observation.url,
                published_at=nc_observation.published_at,
                extraction_location="title and abstract",
            )
        )
        session.add(
            Interpretation(
                observation_id=nc_observation.id,
                content_hash="c" * 64,
                status="collection_only",
            )
        )
        session.add(
            Project(
                identity_key="legacy-nc-commerce-test",
                name="Synthetic manufacturing announcement",
                location="North Carolina",
                source_id=nc_observation.source_id,
                external_id=nc_observation.external_id,
            )
        )
        session.flush()
        nc_project = session.scalar(
            select(Project).where(Project.identity_key == "legacy-nc-commerce-test")
        )
        session.add(
            PowerNeed(
                project_id=nc_project.id,
                activity_key="manufacturing",
                tier="Signal",
                rationale="Existing linked record",
            )
        )
        for index, (title, abstract) in enumerate(
            (
                ("Uncultivated insurance commentary", "No event stated."),
                ("Grow", "facility licensing note."),
            )
        ):
            version = Observation(
                source_id="mjbizdaily-news",
                external_id=f"adversarial-{index}",
                title=title,
                abstract=abstract,
                published_at=datetime(2026, 9, 19).date(),
                url=f"https://mjbizdaily.com/news/adversarial-{index}/",
                content_hash=str(index) * 64,
            )
            session.add(version)
            session.flush()
            session.add(
                Evidence(
                    observation_id=version.id,
                    content_hash=str(index) * 64,
                    title=title,
                    abstract=abstract,
                    url=version.url,
                    published_at=version.published_at,
                    extraction_location="RSS item title and description/summary",
                )
            )
    client = TestClient(app)
    assert client.get("/api/ingestion").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    page = client.get("/api/ingestion?source_id=mjbizdaily-news&vertical=cannabis&limit=1").json()
    assert page["total"] == 4 and len(page["items"]) == 1
    second = client.get("/api/ingestion?source_id=mjbizdaily-news&limit=1&offset=1").json()
    assert second["items"][0]["content_hash"] != page["items"][0]["content_hash"]
    assert page["items"][0]["qualification_state"] == "Not assessed"
    all_items = client.get("/api/ingestion?limit=10").json()
    assert all_items["total"] == 5
    assert (
        client.get("/api/ingestion?source_id=nc-commerce").json()["items"][0]["qualification_state"]
        == "Not assessed"
    )
    assert all(
        "topic_label" not in item and "matched_terms" not in item for item in all_items["items"]
    )
