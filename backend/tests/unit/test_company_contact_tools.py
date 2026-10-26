import importlib.util
import json
import sys
import types
from pathlib import Path
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "company_contact_enrichment", ROOT / "scripts" / "company_contact_enrichment.py"
)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)
_load_manifest = tool._load_manifest
_manifest_digest = tool._manifest_digest
enqueue_manifest = tool.enqueue_manifest
priority = tool._priority
run_manifest_jobs = tool.run_manifest_jobs
persisted_metrics = tool._persisted_contact_metrics
build_plan_manifest = tool.build_plan_manifest
validate_job_binding = tool.validate_job_binding
unique_contact_methods = tool._unique_contact_methods


def test_manifest_accepts_only_ids_and_url_hints(tmp_path: Path):
    company = str(uuid4())
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "companies": [
                    {"company_id": company, "candidate_urls": ["https://acme.example/contact"]}
                ]
            }
        ),
        encoding="utf-8",
    )
    assert _load_manifest(manifest_path)["companies"][0]["company_id"] == company


def test_official_roster_requires_a_real_adjacent_occupational_title():
    from datetime import UTC, datetime

    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import Extracted, extract_people

    observed = datetime(2026, 10, 25, tzinfo=UTC)
    doc = PublicDocument(
        "https://egai.us/about/",
        "About EG AI Corp",
        "The Team\nDennis Finster\nCEO\nDanny Cruz\nCOO\n"
        "Merritt Eaton\nCOO\nGo Live\nComplete Phase 1 construction\n"
        "© 2026 EG AI Corp. All rights reserved.",
        observed_at=observed,
    )
    people = extract_people(
        doc,
        [Extracted("EG AI CORP", "owner_developer", organization_relationship="DIRECT")],
        types.SimpleNamespace(name="Dallas Data Center", identity_facts={}, location="Dallas"),
        project_scoped=False,
        today=observed.date(),
        verified_official_roster=True,
    )
    assert {(row.person_name, row.title) for row in people} == {
        ("Danny Cruz", "COO"),
        ("Merritt Eaton", "COO"),
    }
    assert all("Go Live" not in citation["quote"] for row in people for citation in row.citations)


def test_directory_subject_jsonld_does_not_establish_site_publisher():
    from gridlens.ingestion.adapters.buying_chain_public import parse_document
    from gridlens.intelligence.company_contact_discovery import _self_identified_company_site

    url = "https://www.buckheadenergy.com/operators/de-central-operating-llc"
    html = """<html><head><title>DE Central Operating LLC | Operator Profile</title>
    <script type="application/ld+json">{"@graph":[
      {"@context":"https://schema.org","@type":"Organization",
       "@id":"https://www.buckheadenergy.com/#organization",
       "name":"Buckhead Energy","url":"https://www.buckheadenergy.com/",
       "email":"land@buckheadenergy.com"},
      {"@context":"https://schema.org","@type":"Organization",
       "name":"DE Central Operating LLC",
       "url":"https://www.buckheadenergy.com/operators/de-central-operating-llc"}
    ]}</script></head><body><main>
      <h1>DE Central Operating LLC</h1><p>Listed operator profile.</p>
      <p>Email: land@buckheadenergy.com</p>
      <a href="/contact/">Contact</a></main>
      <footer>© 2026 Buckhead Energy</footer></body></html>"""
    document = parse_document(url, html.encode(), "text/html")
    assert len(document.structured) == 2
    assert document.links == ("https://www.buckheadenergy.com/contact/",)
    assert not _self_identified_company_site(document, "DE Central Operating LLC")
    assert _self_identified_company_site(document, "Buckhead Energy")


def test_official_jsonld_requires_unambiguous_root_publisher():
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument, parse_document
    from gridlens.intelligence.company_contact_discovery import _self_identified_company_site

    url = "https://acme.example/team"
    root = {
        "@type": "Organization",
        "name": "Acme Corp",
        "@id": "https://acme.example/#organization",
    }
    other = {"@type": "Organization", "name": "Other LLC", "url": "https://acme.example/"}
    profile = {"@type": "Organization", "name": "Acme Corp", "url": url}
    assert _self_identified_company_site(
        PublicDocument(url, "Acme Team", "Acme team contact details.", structured=(root,)),
        "Acme Corp",
    )
    assert _self_identified_company_site(
        PublicDocument(
            url,
            "Acme Team",
            "Acme team contact details.",
            structured=({**root, "url": "https://acme.example"},),
        ),
        "Acme Corp",
    )
    assert not _self_identified_company_site(
        PublicDocument(url, "Acme Team", "Acme team contact details.", structured=(profile,)),
        "Acme Corp",
    )
    assert not _self_identified_company_site(
        PublicDocument(
            url,
            "Acme Team",
            "Acme team contact details.",
            structured=({**profile, "@id": "https://acme.example/#organization"},),
        ),
        "Acme Corp",
    )
    first_party_html = """<html><head><title>Acme Corp | Contact</title>
    <script type="application/ld+json">{"@type":"Organization","name":"Acme Corp",
    "@id":"https://acme.example/#organization","url":"https://acme.example/"}</script>
    </head><body><main>Acme Corp corporate contact. Email: info@acme.example.</main>
    <footer>© 2026 Acme Corp. All rights reserved.</footer></body></html>"""
    assert _self_identified_company_site(
        parse_document("https://acme.example/contact", first_party_html.encode(), "text/html"),
        "Acme Corp",
    )
    assert _self_identified_company_site(
        PublicDocument(
            "https://activeironenergy.com/contact-us",
            "Active Iron Energy Contact",
            "Contact Active Iron Energy.\n© 2026 Active Iron Energy LLC. All rights reserved.",
        ),
        "ACTIVE IRON ENERGY LLC",
    )
    assert not _self_identified_company_site(
        PublicDocument(url, "Acme Team", "Acme team contact details.", structured=(root, other)),
        "Acme Corp",
    )
    assert not _self_identified_company_site(
        PublicDocument(
            url,
            "Acme Team",
            "Acme team contact details.\n© 2026 Other LLC",
            structured=(root,),
        ),
        "Acme Corp",
    )


def test_actual_benchmark_manifest_is_reduced_to_ids_and_url_hints(tmp_path: Path):
    company = str(uuid4())
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "selection": "snapshot description",
                "source_snapshot_sha256": "a" * 64,
                "companies": [
                    {
                        "company_identity_id": company,
                        "name": "Acme Corporation",
                        "tiers": ["Signal"],
                        "industries": ["data_center"],
                        "project_count": 2,
                        "candidate_urls": ["https://acme.example/contact"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = _load_manifest(path)
    assert result["companies"] == [
        {"company_id": company, "candidate_urls": ["https://acme.example/contact"]}
    ]
    assert result["source_snapshot_sha256"] == "a" * 64


@pytest.mark.parametrize(
    "row",
    [
        {"company_id": str(uuid4()), "email": "person@example.com"},
        {"company_id": str(uuid4()), "candidate_urls": ["http://acme.example"]},
        {"company_id": str(uuid4()), "candidate_urls": ["https://user:pass@acme.example"]},
        {"company_id": str(uuid4()), "candidate_urls": ["https://acme.example"] * 5},
    ],
)
def test_manifest_rejects_contact_values_and_unsafe_or_unbounded_urls(tmp_path: Path, row):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"companies": [row]}), encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        _load_manifest(path)


def test_manifest_digest_is_stable_and_checkpoint_rejects_changed_manifest():
    company = str(uuid4())
    manifest = {"companies": [{"company_id": company, "candidate_urls": []}]}
    assert _manifest_digest(manifest) == _manifest_digest(json.loads(json.dumps(manifest)))
    with pytest.raises(ValueError, match="digest"):
        enqueue_manifest(object(), manifest, {"manifest_digest": "wrong", "completed": {}})


def test_priority_orders_lead_then_high_value_prospect_then_prospect_then_signal():
    rows = [
        {"company_id": "signal", "tiers": ["Signal"], "priority_rank": 100},
        {"company_id": "prospect-low", "tiers": ["Prospect"], "priority_rank": 2},
        {"company_id": "lead", "tiers": ["Lead"], "priority_rank": 1},
        {"company_id": "prospect-high", "tiers": ["Prospect"], "priority_rank": 90},
    ]
    assert [row["company_id"] for row in priority({"companies": rows})] == [
        "lead",
        "prospect-high",
        "prospect-low",
        "signal",
    ]


def test_read_only_plan_pages_keep_snapshot_and_tier_rank_order():
    inventory = {
        "companies": [
            {
                "company_id": "signal",
                "tiers": ["Signal"],
                "industries": ["oil"],
                "priority_rank": 100,
            },
            {
                "company_id": "lead",
                "tiers": ["Lead"],
                "industries": ["data_center"],
                "priority_rank": 1,
            },
            {
                "company_id": "prospect-a",
                "tiers": ["Prospect"],
                "industries": ["oil"],
                "priority_rank": 40,
            },
            {
                "company_id": "prospect-b",
                "tiers": ["Prospect"],
                "industries": ["oil"],
                "priority_rank": 80,
            },
        ]
    }
    first = build_plan_manifest(inventory, limit=2)
    assert [row["company_id"] for row in first["companies"]] == ["lead", "prospect-b"]
    assert first["next_cursor"] == "prospect-b"
    second = build_plan_manifest(
        inventory,
        limit=2,
        after_company_id=first["next_cursor"],
        expected_snapshot_sha256=first["plan_snapshot_sha256"],
    )
    assert [row["company_id"] for row in second["companies"]] == ["prospect-a", "signal"]
    assert second["next_cursor"] is None
    inventory["companies"][0]["priority_rank"] = 101
    with pytest.raises(ValueError, match="snapshot changed"):
        build_plan_manifest(
            inventory,
            after_company_id="prospect-b",
            expected_snapshot_sha256=first["plan_snapshot_sha256"],
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"kind": "ingestion"},
        {"target_id": str(uuid4())},
        {"payload": {"company_identity_id": "wrong", "candidate_urls": ["https://acme.example"]}},
        {
            "payload": {
                "company_identity_id": "company",
                "candidate_urls": ["https://other.example"],
            }
        },
    ],
)
def test_job_binding_refuses_wrong_kind_target_or_url_payload(updates):
    payload = {"company_identity_id": "company", "candidate_urls": ["https://acme.example"]}
    job = types.SimpleNamespace(
        kind="company_contact_discovery",
        target_id="company",
        checkpoint=json.dumps({"task_type": "company_contact_discovery", "payload": payload}),
    )
    for key, value in updates.items():
        if key == "payload":
            job.checkpoint = json.dumps(
                {"task_type": "company_contact_discovery", "payload": value}
            )
        else:
            setattr(job, key, value)
    with pytest.raises(ValueError, match="does not match"):
        validate_job_binding(job, "company", ["https://acme.example"])


def test_job_binding_keeps_no_hint_manifest_stable_after_discovery():
    payload = {"company_identity_id": "company", "candidate_urls": []}
    job = types.SimpleNamespace(
        kind="company_contact_discovery",
        target_id="company",
        checkpoint=json.dumps({"task_type": "company_contact_discovery", "payload": payload}),
    )
    validate_job_binding(job, "company", [])
    payload["candidate_urls"] = ["https://acme.example/contact"]
    job.checkpoint = json.dumps({"task_type": "company_contact_discovery", "payload": payload})
    with pytest.raises(ValueError, match="does not match"):
        validate_job_binding(job, "company", [])


def test_adaptive_contact_fetch_budget_is_bounded_and_gap_driven():
    from gridlens.intelligence.company_contact_discovery import (
        MAX_ADAPTIVE_FETCHES,
        MAX_CANDIDATE_URLS,
        _adaptive_fetch_limit,
    )
    from gridlens.intelligence.enrichment_planner import (
        DEEP_RESEARCH_PROFILE,
        STANDARD_RESEARCH_PROFILE,
    )

    assert _adaptive_fetch_limit(DEEP_RESEARCH_PROFILE) == MAX_ADAPTIVE_FETCHES
    assert _adaptive_fetch_limit(STANDARD_RESEARCH_PROFILE) == MAX_CANDIDATE_URLS
    assert _adaptive_fetch_limit("unknown-profile") == MAX_CANDIDATE_URLS


@pytest.mark.parametrize(
    "role", ["owner construction", "owner energy", "owner_construction", "owner_energy"]
)
def test_owner_specialist_method_closes_role_gap_without_inventing_authority(role):
    from gridlens.domain.opportunity_intelligence import IntelligenceContact
    from gridlens.intelligence.company_contact_discovery import _has_buyer_relevant_method

    contact = IntelligenceContact(
        claim_id="fixture-claim",
        company="Fixture Energy",
        name="Fixture Contact",
        role=role,
        responsibility="Verified organizational responsibility",
        methods=[{"kind": "email", "href": "mailto:contact@example.test"}],
    )
    authority = contact.purchasing_authority
    assert _has_buyer_relevant_method([contact])
    assert contact.purchasing_authority == authority
    assert "confirmation" in authority
    assert not _has_buyer_relevant_method([contact.model_copy(update={"methods": []})])
    assert not _has_buyer_relevant_method([contact.model_copy(update={"role": "epc"})])


def test_enqueue_resumes_completed_company_and_passes_only_url_hints(monkeypatch):
    company = str(uuid4())
    url = "https://acme.example/contact"
    manifest = {"companies": [{"company_id": company, "candidate_urls": [url]}]}
    calls = []

    job_id = str(uuid4())

    discovery = types.ModuleType("gridlens.intelligence.company_contact_discovery")
    discovery.discover_company_contacts = lambda session, identity, *, candidate_urls: calls.append(
        (identity, candidate_urls)
    ) or {"job_id": job_id, "status": "queued"}
    monkeypatch.setitem(sys.modules, discovery.__name__, discovery)
    result = enqueue_manifest(object(), manifest)
    assert calls == [(UUID(company), [url])]
    assert result["completed"][company]["status"] == "queued"
    assert result["completed"][company]["job_id"] == job_id
    assert result["provider_cost_usd"] == "UNKNOWN"
    calls.clear()
    resumed = enqueue_manifest(object(), manifest, result)
    assert calls == []
    assert resumed["enqueued_this_run"] == []


def test_run_jobs_executes_exact_queued_id_and_persists_metrics(monkeypatch, tmp_path: Path):
    company, job_id = str(uuid4()), str(uuid4())
    terminal_company, terminal_job_id = str(uuid4()), str(uuid4())
    manifest = {
        "companies": [
            {"company_id": company, "candidate_urls": []},
            {"company_id": terminal_company, "candidate_urls": []},
        ]
    }
    terminal_job = types.SimpleNamespace(
        id=UUID(terminal_job_id),
        kind="company_contact_discovery",
        target_id=terminal_company,
        status="succeeded",
        error=None,
        attempts=1,
        checkpoint=json.dumps(
            {
                "task_type": "company_contact_discovery",
                "payload": {"company_identity_id": terminal_company, "candidate_urls": []},
                "status": "complete",
                "checked_urls": [],
            }
        ),
    )
    checkpoint = {
        "manifest_digest": _manifest_digest(manifest),
        "completed": {
            company: {"status": "queued", "job_id": job_id},
            terminal_company: {"status": "queued", "job_id": terminal_job_id},
        },
    }
    job = types.SimpleNamespace(
        id=UUID(job_id),
        kind="company_contact_discovery",
        target_id=company,
        status="queued",
        error=None,
        attempts=0,
        checkpoint=json.dumps(
            {
                "task_type": "company_contact_discovery",
                "payload": {"company_identity_id": company, "candidate_urls": []},
            }
        ),
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _identity):
            return terminal_job if _identity == UUID(terminal_job_id) else job

    model_module = types.ModuleType("gridlens.persistence.models")
    model_module.Job = type("Job", (), {})
    contacts_module = types.ModuleType("gridlens.intelligence.company_contacts")
    contacts_module.company_contacts = lambda *_args: types.SimpleNamespace(
        contacts=[], research_required=True
    )
    contacts_module.relevant_named_contact = lambda _contact: False
    contacts_module.relevant_named_professional = lambda _contact: False
    worker_module = types.ModuleType("gridlens.jobs.worker")
    called = []

    def run_one(_definitions, *, job_ids):
        called.extend(job_ids)
        job.status = "succeeded"
        job.checkpoint = json.dumps({"status": "complete", "checked_urls": []})
        return True

    worker_module.run_one = run_one
    monkeypatch.setitem(sys.modules, model_module.__name__, model_module)
    monkeypatch.setitem(sys.modules, contacts_module.__name__, contacts_module)
    monkeypatch.setitem(sys.modules, worker_module.__name__, worker_module)
    result = run_manifest_jobs(Session, manifest, checkpoint, tmp_path / "checkpoint.json")
    assert called == [UUID(job_id)]
    assert result["completed"][company]["run_status"] == "complete"
    assert result["completed"][company]["persisted_contacts"]["usable_email_or_phone"] is False
    assert result["provider_cost_usd"] == "UNKNOWN"
    assert result["run_summary"]["companies_with_terminal_job"] == 2
    assert result["run_summary"]["metrics"]["verified_email_methods"] == 0


def test_run_jobs_does_not_repeat_in_flight_job(monkeypatch, tmp_path: Path):
    company, job_id = str(uuid4()), str(uuid4())
    manifest = {"companies": [{"company_id": company, "candidate_urls": []}]}
    checkpoint = {
        "manifest_digest": _manifest_digest(manifest),
        "completed": {company: {"status": "queued", "job_id": job_id}},
    }
    job = types.SimpleNamespace(
        id=UUID(job_id),
        kind="company_contact_discovery",
        target_id=company,
        status="running",
        error=None,
        attempts=1,
        checkpoint=json.dumps(
            {
                "task_type": "company_contact_discovery",
                "payload": {"company_identity_id": company, "candidate_urls": []},
            }
        ),
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _identity):
            return job

    model_module = types.ModuleType("gridlens.persistence.models")
    model_module.Job = type("Job", (), {})
    worker_module = types.ModuleType("gridlens.jobs.worker")
    worker_module.run_one = lambda *_args, **_kwargs: pytest.fail("must not retry an in-flight job")
    monkeypatch.setitem(sys.modules, model_module.__name__, model_module)
    monkeypatch.setitem(sys.modules, worker_module.__name__, worker_module)
    result = run_manifest_jobs(Session, manifest, checkpoint, tmp_path / "checkpoint.json")
    assert result["completed"][company]["run_status"] == "in_flight"


def test_run_jobs_refuses_arbitrary_job_before_worker_lease(monkeypatch, tmp_path: Path):
    company, job_id = str(uuid4()), str(uuid4())
    manifest = {"companies": [{"company_id": company, "candidate_urls": []}]}
    checkpoint = {
        "manifest_digest": _manifest_digest(manifest),
        "completed": {company: {"status": "queued", "job_id": job_id}},
    }
    job = types.SimpleNamespace(
        id=UUID(job_id),
        kind="ingestion",
        target_id=company,
        status="queued",
        error=None,
        attempts=0,
        checkpoint=json.dumps(
            {
                "task_type": "company_contact_discovery",
                "payload": {"company_identity_id": company, "candidate_urls": []},
            }
        ),
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _identity):
            return job

    model_module = types.ModuleType("gridlens.persistence.models")
    model_module.Job = type("Job", (), {})
    worker_module = types.ModuleType("gridlens.jobs.worker")
    worker_module.run_one = lambda *_args, **_kwargs: pytest.fail("arbitrary job must not run")
    monkeypatch.setitem(sys.modules, model_module.__name__, model_module)
    monkeypatch.setitem(sys.modules, worker_module.__name__, worker_module)
    with pytest.raises(ValueError, match="does not match"):
        run_manifest_jobs(Session, manifest, checkpoint, tmp_path / "checkpoint.json")


def test_persisted_metrics_separate_person_methods_from_generic_company_routes(monkeypatch):
    from types import SimpleNamespace

    contacts_module = types.ModuleType("gridlens.intelligence.company_contacts")
    people = [
        SimpleNamespace(
            name="Alex Example",
            company="Acme",
            title="Facilities Director",
            role="facilities",
            responsibility="Verified organizational responsibility",
            purchasing_authority="unconfirmed",
            methods=[{"kind": "email", "href": "mailto:alex@example.test"}],
            sources=[
                SimpleNamespace(model_dump=lambda **_kwargs: {"url": "https://example.test/team"})
            ],
            verified_at="2026-10-25T00:00:00Z",
        ),
        SimpleNamespace(
            name=None,
            company="Acme",
            title=None,
            role="unknown",
            responsibility="General company contact path",
            purchasing_authority="unconfirmed",
            methods=[{"kind": "phone", "href": "tel:+15550000000"}],
            sources=[],
            verified_at="2026-10-25T00:00:00Z",
        ),
    ]
    contacts_module.company_contacts = lambda *_args: SimpleNamespace(
        contacts=people, research_required=False
    )
    contacts_module.relevant_named_contact = lambda contact: contact.name is not None
    contacts_module.relevant_named_professional = lambda contact: contact.name is not None
    monkeypatch.setitem(sys.modules, contacts_module.__name__, contacts_module)
    report = persisted_metrics(object(), uuid4())
    assert report["direct_person_email_methods"] == 1
    assert report["generic_company_phone_methods"] == 1
    assert report["usable_email_or_phone"] is True
    assert report["purchasing_authority"] == "unconfirmed"
    assert report["contacts"][0]["sources"][0]["url"] == "https://example.test/team"


def test_method_projection_deduplicates_by_person_company_kind_and_href():
    from types import SimpleNamespace

    contacts = [
        SimpleNamespace(
            name="Alex Example",
            company="Acme",
            methods=[{"kind": "Email", "href": "MAILTO:alex@example.test"}],
        ),
        SimpleNamespace(
            name=" alex example ",
            company="Acme",
            methods=[{"kind": "email", "href": "mailto:alex@example.test"}],
        ),
        SimpleNamespace(
            name=None, company="Acme", methods=[{"kind": "phone", "href": "tel:+15550001111"}]
        ),
        SimpleNamespace(
            name=None, company=" acme ", methods=[{"kind": "PHONE", "href": "TEL:+15550001111"}]
        ),
    ]
    assert len(unique_contact_methods(contacts)) == 2


def test_url_only_method_is_not_counted_as_usable_email_or_phone(monkeypatch):
    contact = types.SimpleNamespace(
        name="Alex Example",
        company="Acme",
        title="Facilities Director",
        role="facilities",
        responsibility="Verified organizational responsibility",
        purchasing_authority="unconfirmed",
        methods=[{"kind": "web", "value": "Contact page", "href": "https://acme.example/contact"}],
        sources=[],
        verified_at=None,
    )
    contacts_module = types.ModuleType("gridlens.intelligence.company_contacts")
    contacts_module.company_contacts = lambda *_args: types.SimpleNamespace(
        contacts=[contact], research_required=True
    )
    contacts_module.relevant_named_contact = lambda _contact: False
    contacts_module.relevant_named_professional = lambda _contact: False
    monkeypatch.setitem(sys.modules, contacts_module.__name__, contacts_module)
    report = persisted_metrics(object(), uuid4())
    assert report["verified_email_methods"] == 0
    assert report["verified_phone_methods"] == 0
    assert report["usable_email_or_phone"] is False
    assert report["url_only_route"] is True


def test_methodless_named_professional_is_counted_without_inventing_buyer_contact(monkeypatch):
    from types import SimpleNamespace

    person = SimpleNamespace(
        name="Gregory Example",
        company="Acme",
        title="Vice President, Supply Chain",
        role="supply_chain",
        responsibility="Verified organizational responsibility",
        purchasing_authority="unconfirmed",
        methods=[],
        sources=[],
        verified_at="2026-10-25T00:00:00Z",
    )
    contacts_module = types.ModuleType("gridlens.intelligence.company_contacts")
    contacts_module.company_contacts = lambda *_args: SimpleNamespace(
        contacts=[person], research_required=True
    )
    contacts_module.relevant_named_professional = lambda contact: bool(
        contact.name and contact.responsibility == "Verified organizational responsibility"
    )
    monkeypatch.setitem(sys.modules, contacts_module.__name__, contacts_module)

    report = persisted_metrics(object(), uuid4())

    assert report["named_relevant_professionals"] == 1
    assert report["named_people_without_methods"] == 1
    assert report["usable_email_or_phone"] is False
    assert report["direct_person_email_methods"] == 0
    assert report["direct_person_phone_methods"] == 0
    assert report["purchasing_authority"] == "unconfirmed"
    assert report["source_confirmed_project_decision_maker"] == "UNKNOWN"
