"""Real-PostgreSQL scheduled research and projection acceptance on a synthetic fixture."""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import subprocess
import time
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import gridlens
from gridlens.intelligence import saved_browse
from gridlens.intelligence.customer_accounts import account_projects
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseRow,
    CompanyIdentity,
    Evidence,
    ExternalImportActivation,
    ExternalImportBatch,
    ExternalImportRow,
    Interpretation,
    Job,
    LogicalCall,
    NeedObservation,
    Observation,
    PlannerState,
    PowerNeed,
    Project,
    PursuitResearchQuestion,
    Source,
)
from gridlens.settings import settings

ROOT = Path(__file__).resolve().parents[3]
MODE_DATABASES = {
    "baseline": "gl3_phase2_baseline_fixture_test",
    "candidate": "gl3_phase2_candidate_fixture_test",
}
ROUTING_ENV = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGOPTIONS",
    "PGSERVICE",
    "PGSERVICEFILE",
)


def _check_url(value: str, *, expected_database: str | None = None):
    parsed = make_url(value)
    assert parsed.drivername in {"postgresql", "postgresql+psycopg"}
    assert parsed.host in {"127.0.0.1", "localhost", "::1"}
    if expected_database is not None:
        assert parsed.port == 58744
        assert parsed.username == "gridlens" and parsed.password is None
    else:
        assert 1 <= parsed.port <= 65535
    assert parsed.database
    assert not urlsplit(value).fragment
    assert not {
        "host",
        "hostaddr",
        "port",
        "dbname",
        "database",
        "user",
        "username",
        "password",
        "service",
        "servicefile",
        "options",
        "target_session_attrs",
    }.intersection(parsed.query)
    assert not any(os.environ.get(key) for key in ROUTING_ENV)
    from sqlalchemy.dialects.postgresql.psycopg import dialect

    args, effective = dialect().create_connect_args(parsed)
    assert not args
    assert effective.get("host") in {"127.0.0.1", "localhost", "::1"}
    if expected_database is not None:
        assert effective.get("port") == 58744
    else:
        assert effective.get("port") == parsed.port
    assert effective.get("dbname") == parsed.database
    if expected_database is not None:
        assert parsed.database == expected_database
    return parsed


@pytest.fixture
def phase2_db(monkeypatch):
    requested_mode = os.environ.get("PHASE2_ACCEPTANCE_MODE")
    assert requested_mode is None or requested_mode in MODE_DATABASES
    mode = requested_mode or "candidate"
    app_url = _check_url(settings.database_url)
    test_url = _check_url(settings.test_database_url)
    if requested_mode:
        _check_url(settings.database_url, expected_database="gl3_phase2_acceptance_app")
        _check_url(settings.test_database_url, expected_database=MODE_DATABASES[mode])
    else:
        assert test_url.database and test_url.database.endswith("_test")
        assert "corpus" not in test_url.database.lower()
    assert (app_url.host, app_url.port, app_url.database) != (
        test_url.host,
        test_url.port,
        test_url.database,
    )
    imported = Path(gridlens.__file__).resolve()
    source_root = Path(os.environ.get("PHASE2_EXPECTED_SOURCE_ROOT", imported.parents[1])).resolve()
    assert imported.is_relative_to(source_root), (
        f"Imported GridLens source {imported} is outside selected source root {source_root}"
    )
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source_root.parents[1], text=True
    ).strip()
    declared_commit = os.environ.get("PHASE2_SOURCE_COMMIT")
    if declared_commit:
        assert source_commit == declared_commit
    if requested_mode == "baseline":
        assert source_commit == "bc433650ce4706dddfb5b30d78a502e3b528f54e"
    if requested_mode == "candidate":
        assert source_commit != "bc433650ce4706dddfb5b30d78a502e3b528f54e"

    # The explicitly reserved task databases must be empty. CI uses a random
    # private schema inside its separately guarded disposable *_test DB.
    engine = create_engine(settings.test_database_url, pool_size=6)
    schema = "phase2_acceptance_" + uuid4().hex
    admin = engine
    try:
        if requested_mode:
            assert inspect(engine).get_table_names(schema="public") == [], (
                "Refusing a non-pristine task-owned fixture database"
            )
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = create_engine(
            settings.test_database_url,
            pool_size=6,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(scoped)
        with scoped.begin() as connection:
            install(connection)
        factory = sessionmaker(scoped, expire_on_commit=False)

        from importlib import import_module

        api_module = import_module("gridlens.api.app")
        from gridlens.intelligence import autonomous_research
        from gridlens.intelligence import company_contact_discovery as contacts_module
        from gridlens.jobs import worker

        monkeypatch.setattr(api_module, "SessionLocal", factory)
        monkeypatch.setattr(autonomous_research, "SessionLocal", factory)
        monkeypatch.setattr(contacts_module, "SessionLocal", factory)
        monkeypatch.setattr(worker, "SessionLocal", factory)
        monkeypatch.setattr(settings, "worker_auto_refresh", True)
        monkeypatch.setattr(settings, "autonomous_research_enabled", True)
        monkeypatch.setattr(settings, "company_contact_discovery_enabled", True)
        monkeypatch.setattr(settings, "firecrawl_api_key", None)
        monkeypatch.setattr(settings, "openai_api_key", None)
        monkeypatch.setattr(settings, "typesafe_api_key", None)
        monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", 0)
        monkeypatch.setattr(settings, "intelligence_max_call_usd", 0)
        yield factory, worker, api_module, scoped, mode
        scoped.dispose()
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed_fixture(factory):
    """Three distinct sites, four need records, and a separate similar-name owner."""
    sites = [
        ("site-a", "Synthetic Acme Site A", "811 Fixture Road, Austin, TX"),
        ("site-b", "Synthetic Acme Site B", "200 Fixture Avenue, Austin, TX"),
        ("site-c", "Synthetic Acme Campus C", "400 Campus Test Drive, Austin, TX"),
    ]
    fact_specs = [
        ("site-a", "construction-temporary", "2.4 MW temporary construction load"),
        ("site-a", "commissioning", "commissioning power amount is not stated"),
        ("site-b", "construction-temporary", "1.5 MW temporary construction load"),
        (
            "site-c",
            "campus-capacity",
            "40 MW campus nameplate; no temporary rental load stated",
        ),
    ]
    fixture_facts = {
        "version": "phase2-cross-lane-synthetic-v3",
        "sites": sites,
        "needs": fact_specs,
        "reserved_domain": "acme.test",
        "identity_source": "texas-rrc-drilling-permits",
        "activity_source": "austin-building-permits",
        "public_contact_path": "synthetic-self-identified-acme-root",
    }
    fixture_input_sha256 = _digest(json.dumps(fixture_facts, sort_keys=True, separators=(",", ":")))
    fixture_id = "phase2-cross-lane-v3-" + fixture_input_sha256
    with factory.begin() as session:
        session.add(
            Source(
                id="texas-rrc-drilling-permits",
                publisher="Synthetic Phase 2 fixture",
                endpoint="https://example.invalid/",
                family="construction-permits",
                geography="Texas",
                industries=["data-center"],
                retrieval_method="rrc-drilling-permits",
                health={},
            )
        )
        session.add(
            Source(
                id="austin-building-permits",
                publisher="Synthetic Phase 2 fixture",
                endpoint="https://example.invalid/austin-permits",
                family="construction-permits",
                geography="Austin, TX",
                industries=["data-center"],
                retrieval_method="socrata-permits",
                health={},
            )
        )
        session.flush()
        operator = CompanyIdentity(rrc_operator_number="000001")
        lookalike = CompanyIdentity(rrc_operator_number="000002")
        session.add_all([operator, lookalike])
        session.flush()
        projects = {}
        for key, name, location in sites:
            project = Project(
                identity_key=f"{fixture_id}:{key}",
                name=name,
                location=location,
                source_id="texas-rrc-drilling-permits",
                external_id=f"synthetic-permit-site-{len(projects) + 1}",
                identity_facts={"synthetic_fixture": fixture_id, "site_key": key},
                asset_type="data_center",
                region_status="ELIGIBLE",
            )
            session.add(project)
            session.flush()
            projects[key] = project
            evidence = Evidence(
                observation_id=uuid4(),
                content_hash=_digest(f"{fixture_id}:{key}:site-context"),
                title=f"Synthetic owner record for {name}",
                abstract=(
                    f"Project: {name}\nLocation: Texas\nOperator number: 000001\n"
                    f"Operator: Acme Incorporated\nLease: Synthetic lease {key}\n"
                    f"Well: Synthetic well {key}\nSYNTHETIC fixture {fixture_id}. "
                    f"This operator record is separate from any asserted power need. "
                    f"Site context: {name} at {location}. "
                    f"Public operator project page: https://acme.test/projects/{key}."
                ),
                url=f"https://acme.test/projects/{key}",
                published_at=date(2026, 10, 1),
                observed_at=datetime(2026, 11, 7, tzinfo=UTC),
            )
            evidence.content_hash = _digest(evidence.abstract)
            observation = Observation(
                id=evidence.observation_id,
                source_id="texas-rrc-drilling-permits",
                external_id=project.external_id,
                title=evidence.title,
                abstract=evidence.abstract,
                published_at=evidence.published_at,
                url=evidence.url,
                content_hash=evidence.content_hash,
            )
            session.add(observation)
            session.flush()
            session.add(evidence)
            session.flush()
            session.add(
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    evaluator_version="phase2-synthetic-admission-v1",
                    status="accepted",
                    assessment={
                        "project_identity_key": project.identity_key,
                        "decision": "accepted",
                        "semantic_hash": observation.content_hash,
                        "evidence_hash": evidence.content_hash,
                        "evidence": {"id": str(evidence.id), "url": evidence.url},
                        "admission_status": "supplemental",
                        "power_activity": "electrical-construction",
                        "activity_key": "electrical-construction",
                        "subject": project.name,
                        "location": project.location,
                        "action": evidence.abstract,
                        "synthetic_fixture": fixture_id,
                    },
                )
            )
            from gridlens.intelligence.customer_accounts import record_rrc_operator_membership

            record_rrc_operator_membership(
                session,
                project=project,
                observation=observation,
                evidence=evidence,
                source_id="texas-rrc-drilling-permits",
                record={"abstract": evidence.abstract},
            )
            session.flush()
            session.flush()

        for index, (site_key, activity, statement) in enumerate(fact_specs):
            project = projects[site_key]
            evidence = Evidence(
                observation_id=uuid4(),
                content_hash=_digest(f"{fixture_id}:need:{index}"),
                title=f"Synthetic data center construction permit {index}",
                abstract=f"SYNTHETIC fixture {fixture_id}. {project.name}: {statement}.",
                url=f"https://acme.test/records/{site_key}/{activity}",
                published_at=date(2026, 10, 2 + index),
                observed_at=datetime(2026, 11, 7, tzinfo=UTC),
            )
            evidence.abstract = (
                f"Project: {project.name}\nLocation: {project.location}\n"
                f"Work description: New data center construction; {statement}.\n"
                f"Source record: synthetic fixture {fixture_id}."
            )
            evidence.content_hash = _digest(evidence.abstract)
            observation = Observation(
                id=evidence.observation_id,
                source_id="austin-building-permits",
                external_id=f"{fixture_id}:need:{index}",
                title=evidence.title,
                abstract=evidence.abstract,
                published_at=evidence.published_at,
                url=evidence.url,
                content_hash=evidence.content_hash,
            )
            session.add(observation)
            session.flush()
            session.add(evidence)
            session.flush()
            session.add(
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    evaluator_version="phase2-synthetic-admission-v1",
                    status="accepted",
                    assessment={
                        "project_identity_key": project.identity_key,
                        "decision": "accepted",
                        "semantic_hash": observation.content_hash,
                        "evidence_hash": evidence.content_hash,
                        "evidence": {"id": str(evidence.id), "url": evidence.url},
                        "admission_status": "supplemental",
                        "power_activity": activity,
                        "activity_key": activity,
                        "subject": project.name,
                        "location": project.location,
                        "action": evidence.abstract,
                        "synthetic_fixture": fixture_id,
                    },
                )
            )
            need = PowerNeed(
                project_id=project.id,
                activity_key=activity,
                tier="Signal",
                rationale=f"Synthetic source-backed {activity} test need.",
                supply="Unknown",
                active=True,
            )
            session.add(need)
            session.flush()
            session.add(NeedObservation(need_id=need.id, observation_id=observation.id))

        # A matched import supplies only an unverified company-domain hint.
        # The company contact worker still validates that the fetched page
        # identifies the company before retaining any contact claim.
        batch = ExternalImportBatch(
            filename="synthetic-phase2-accounts.xlsx",
            content_hash=_digest(f"{fixture_id}:matched-import"),
            report={},
            metrics={},
            actor="synthetic-phase2-test",
        )
        session.add(batch)
        session.flush()
        import_row = ExternalImportRow(
            batch_id=batch.id,
            sheet="Accounts",
            row_number=2,
            row_kind="company",
            raw={"Company": "Acme Incorporated", "Domain": "acme.test"},
            normalized={"company_name": "Acme Incorporated", "domain": "acme.test"},
            errors=[],
            match_status="matched",
            company_match={"status": "matched", "candidate_id": str(operator.id)},
            project_match={"status": "unmatched", "candidate_id": None},
        )
        session.add(import_row)
        session.flush()
        session.add(
            ExternalImportActivation(
                row_id=import_row.id,
                active=True,
                changed_by="synthetic-phase2-test",
            )
        )

        # A similar name with a conflicting identity is a separate account and
        # has no evidence or contacts borrowed from Acme Incorporated.
        other_project = Project(
            identity_key=f"{fixture_id}:lookalike",
            name="Synthetic Acme Independent Site",
            location="900 Different Owner Lane, Austin, TX",
            source_id="texas-rrc-drilling-permits",
            external_id=f"{fixture_id}:lookalike-source",
            identity_facts={"synthetic_fixture": fixture_id},
            region_status="ELIGIBLE",
        )
        session.add(other_project)
        session.flush()
        lookalike_evidence = Evidence(
            observation_id=uuid4(),
            content_hash=_digest(f"{fixture_id}:lookalike"),
            title="Synthetic independent owner record",
            abstract=(
                f"Project: Synthetic Acme Independent Site\nLocation: Texas\n"
                "Operator number: 000002\nOperator: Acme Incorporated\n"
                "Lease: Synthetic lease lookalike\nWell: Synthetic well lookalike\n"
                f"SYNTHETIC fixture {fixture_id}. This is a separate operator ID "
                "000002 and independent physical site."
            ),
            url="https://acme-conflict.test/project",
            published_at=date(2026, 10, 6),
            observed_at=datetime(2026, 11, 7, tzinfo=UTC),
        )
        lookalike_evidence.content_hash = _digest(lookalike_evidence.abstract)
        lookalike_observation = Observation(
            id=lookalike_evidence.observation_id,
            source_id="texas-rrc-drilling-permits",
            external_id=other_project.external_id,
            title=lookalike_evidence.title,
            abstract=lookalike_evidence.abstract,
            published_at=lookalike_evidence.published_at,
            url=lookalike_evidence.url,
            content_hash=lookalike_evidence.content_hash,
        )
        session.add(lookalike_observation)
        session.flush()
        session.add(lookalike_evidence)
        session.flush()
        lookalike_need = PowerNeed(
            project_id=other_project.id,
            activity_key="unrelated-owner-work",
            tier="Signal",
            rationale="Synthetic separate-owner need; amount and timing remain unknown.",
            supply="Unknown",
            active=True,
        )
        session.add(lookalike_need)
        session.flush()
        session.add(
            Interpretation(
                observation_id=lookalike_observation.id,
                content_hash=lookalike_observation.content_hash,
                evaluator_version="phase2-synthetic-admission-v1",
                status="accepted",
                assessment={
                    "project_identity_key": other_project.identity_key,
                    "decision": "accepted",
                    "semantic_hash": lookalike_observation.content_hash,
                    "evidence_hash": lookalike_evidence.content_hash,
                    "evidence": {
                        "id": str(lookalike_evidence.id),
                        "url": lookalike_evidence.url,
                    },
                    "admission_status": "supplemental",
                    "power_activity": "unrelated-owner-work",
                    "activity_key": "unrelated-owner-work",
                    "subject": other_project.name,
                    "location": other_project.location,
                    "action": lookalike_evidence.abstract,
                    "synthetic_fixture": fixture_id,
                },
            )
        )
        session.add(
            NeedObservation(
                need_id=lookalike_need.id,
                observation_id=lookalike_observation.id,
            )
        )
        from gridlens.intelligence.customer_accounts import record_rrc_operator_membership

        record_rrc_operator_membership(
            session,
            project=other_project,
            observation=lookalike_observation,
            evidence=lookalike_evidence,
            source_id="texas-rrc-drilling-permits",
            record={"abstract": lookalike_evidence.abstract},
        )
        from gridlens.intelligence.buying_chain import enrich_buying_chain

        for project in [*projects.values(), other_project]:
            enrich_buying_chain(session, project.id, retained_only=True)
        session.flush()
        return fixture_id, operator.id, lookalike.id


def _install_http_transport(monkeypatch, *, outage: dict, requests: list[str], mode: str):
    """Route real bounded HTTP code to deterministic MockTransport responses."""
    from importlib import import_module

    import httpx

    adapter = import_module("gridlens.ingestion.adapters.buying_chain_public")
    rrc_directory = import_module("gridlens.ingestion.adapters.rrc_operator_directory")
    rrc_directory._reset_cache_for_tests()
    monkeypatch.setattr(rrc_directory, "_cached_snapshot", None)
    monkeypatch.setattr(rrc_directory, "_cached_at", None)
    if mode == "candidate":
        policy = import_module("gridlens.ingestion.adapters.public_site_policy")
        approvals = [
            {
                "hostname": host,
                "terms_review_ref": f"synthetic-terms-review:{host}",
                "reviewed_at": "2026-11-07T00:00:00+00:00",
                "expires_at": "2027-11-07T00:00:00+00:00",
                "modes": ["direct"],
            }
            for host in ("acme.test", "acme-conflict.test", "webapps2.rrc.texas.gov")
        ]
        monkeypatch.setattr(
            policy.settings,
            "public_research_site_permissions",
            json.dumps(approvals),
        )
    client_type = httpx.Client
    html = b"""<!doctype html>
    <html><head><title>Acme Incorporated synthetic project team</title></head>
    <body><main><h1>Acme Incorporated</h1>
    <p>SYNTHETIC Phase 2 fixture only. Acme Incorporated is the owner and developer
    of these test projects.</p>
    <p>RRC operator number: 000001</p>
    <p>Project contact: Jane Example, Facilities Project Coordinator.</p>
    <p>Owner email: jane@example.acme.test</p>
    <p>Public office: +1 (312) 555-0142</p>
    </main><footer>&copy; 2026 Acme Incorporated</footer></body></html>"""
    conflicting_html = b"""<!doctype html>
    <html><head><title>Acme Incorporated separate synthetic operator</title></head>
    <body><main><h1>Acme Incorporated</h1>
    <p>SYNTHETIC Phase 2 fixture only. This is operator ID A00002, a separate identity.
    <p>RRC operator number: 000002</p>
    No named project buyer or public contact method is published.</p>
    </main></body></html>"""
    rrc_directory_html = b"""<!doctype html><html><body>
    <h1>Organization Operator Query Results</h1>
    <p>Operator Number: 000001</p>
    <p>Operator Name: Acme Incorporated</p>
    <p>Organization Phone No.: (512) 555-0142</p>
    </body></html>"""

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Oil and Gas Directory"
    sheet.append(["11/08/2026 12:01:48 PM"])
    sheet.append([None, None, "Railroad Commission of Texas Oil & Gas P5"])
    sheet.append(
        [
            "Org Number",
            "Org Name",
            "",
            "First Address Line",
            "Second Address Line",
            "Apt/Suite and #",
            "City",
            "State",
            "Zip",
            "Country",
            "Phone",
            "Emergency",
            "Mail Ret'd by PO",
            "P5 Status",
        ]
    )
    sheet.append(
        [
            "000001",
            "Acme Incorporated",
            "",
            "PO Box 1",
            "",
            "",
            "Austin",
            "TX",
            "78701",
            "USA",
            "5125550142",
            "5125550000",
            "No",
            "Active",
        ]
    )
    workbook_bytes = BytesIO()
    workbook.save(workbook_bytes)
    workbook_body = workbook_bytes.getvalue()
    workbook_url = "https://www.rrc.texas.gov/media/phase2/oil-and-gas-directory-11-08-26.xlsx"
    directory_index = f"""<!doctype html><html><head>
      <title>Oil &amp; Gas Directory - Operator Contact Information</title>
      </head><body><p>Railroad Commission of Texas.</p>
      <p>Information available in this query is updated nightly.</p>
      <p>These downloadable files contain data as of November 8th, 2026.</p>
      <a href="{workbook_url}">Oil and Gas Directory, (Excel)</a>
      </body></html>""".encode()

    def respond(request):
        host = request.headers.get("host", "")
        requests.append(f"https://{host}{request.url.raw_path.decode('ascii')}")
        if outage["enabled"]:
            outage["requests"] = outage.get("requests", 0) + 1
            raise httpx.ReadTimeout("synthetic public transport timeout", request=request)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"User-agent: *\nAllow: /\n",
                request=request,
            )
        if host == "www.rrc.texas.gov":
            if request.url.path.endswith(".xlsx"):
                return httpx.Response(
                    200,
                    headers={
                        "content-type": (
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    },
                    content=workbook_body,
                    request=request,
                )
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=directory_index,
                request=request,
            )
        if host == "webapps2.rrc.texas.gov":
            body = rrc_directory_html
        else:
            body = conflicting_html if host == "acme-conflict.test" else html
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=body,
            request=request,
        )

    transport = httpx.MockTransport(respond)

    def client(*args, **kwargs):
        kwargs["transport"] = transport
        kwargs["trust_env"] = False
        return client_type(*args, **kwargs)

    def isolated(function_path, args, kwargs, *, deadline):
        if function_path == ("gridlens.ingestion.adapters.buying_chain_public:_retrieve_direct"):
            return adapter._retrieve_direct(*args, **kwargs)
        if function_path == (
            "gridlens.ingestion.adapters.buying_chain_public:_fetch_robots_direct"
        ):
            return adapter._fetch_robots_direct(*args, **kwargs)
        if function_path == (
            "gridlens.ingestion.adapters.rrc_operator_directory:_retrieve_directory_direct"
        ):
            return rrc_directory._retrieve_directory_direct(*args, **kwargs)
        raise AssertionError(f"Unexpected isolated public transport function: {function_path}")

    monkeypatch.setattr(adapter, "run_isolated", isolated)
    monkeypatch.setattr(rrc_directory, "run_isolated", isolated)
    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(
        adapter.socket,
        "getaddrinfo",
        lambda host, port, type=None: [(2, 1, 6, "", ("8.8.8.8", port or 443))],
    )


def _extract_brief(card: dict) -> dict | None:
    brief = card.get("commercial_brief")
    return brief if isinstance(brief, dict) else None


def _capture_projection(factory, api_module, company_id: UUID, lookalike_id: UUID):
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.intelligence.project_results import page as project_page
    from gridlens.persistence.commercial_pursuit_models import (
        CommercialPursuit,
        PursuitActivity,
        PursuitTask,
    )

    latencies = []
    with factory() as session:
        for _ in range(5):
            started = time.perf_counter()
            account = account_projects(session, company_id, limit=25, offset=0)
            latencies.append((time.perf_counter() - started) * 1000)
        other = account_projects(session, lookalike_id, limit=25, offset=0)
        cards = api_module._commercial_triage_cards(session, 50)
        from gridlens.intelligence.account_shortlist import assess_generation

        generation = saved_browse.current_generation(session)
        legacy_shortlist = assess_generation(session, generation)
        browse_evidence_details = {}
        for row in session.scalars(
            select(BrowseRow).where(BrowseRow.generation_id == generation.id)
        ):
            refs = (row.summary or {}).get("evidence", [])
            browse_evidence_details[str(row.need_id)] = [
                {
                    "id": str(reference.get("id") or ""),
                    "assessment_current": reference.get("assessment_current") is True,
                    "source_id": reference.get("source_id"),
                }
                for reference in refs
            ]
        project_projection = project_page(
            session,
            limit=50,
            shortlist=True,
            primary_customer_ids_by_project={
                str(item["id"]): str(company_id) for item in account["items"]
            },
        )
        primary_contacts = company_contacts(session, company_id).contacts
        other_contacts = company_contacts(session, lookalike_id).contacts
        evidence = {
            str(row.id): {
                "url": row.url,
                "abstract": row.abstract or "",
                "content_hash": row.content_hash,
            }
            for row in session.scalars(select(Evidence))
        }
        current_evidence_by_need: dict[str, dict[str, dict]] = {}
        current_rows = session.execute(
            select(NeedObservation.need_id, Project, Observation, Evidence, Interpretation)
            .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
            .join(Project, Project.id == PowerNeed.project_id)
            .join(Observation, Observation.id == NeedObservation.observation_id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .join(Interpretation, Interpretation.observation_id == Observation.id)
            .where(
                NeedObservation.need_id.in_(
                    [need["id"] for project in account["items"] for need in project["needs"]]
                )
            )
        ).all()
        for need_id, project_row, observation_row, evidence_row, interpretation in current_rows:
            assessment = interpretation.assessment or {}
            if not (
                evidence_row.observation_id == observation_row.id
                and evidence_row.content_hash == observation_row.content_hash
                and interpretation.status == "accepted"
                and interpretation.content_hash == observation_row.content_hash
                and assessment.get("decision") == "accepted"
                and assessment.get("evidence_hash") == evidence_row.content_hash
                and assessment.get("semantic_hash") == observation_row.content_hash
                and assessment.get("project_identity_key") == project_row.identity_key
                and (assessment.get("evidence") or {}).get("id") == str(evidence_row.id)
            ):
                continue
            from gridlens.domain.signal_admission import admitted_from_source

            source_row = session.get(Source, observation_row.source_id)
            if (
                source_row is None
                or not admitted_from_source(source_row, assessment, evidence_row).admitted
            ):
                continue
            current_evidence_by_need.setdefault(str(need_id), {})[str(evidence_row.id)] = {
                "url": evidence_row.url,
                "content_hash": evidence_row.content_hash,
                "abstract": evidence_row.abstract or "",
                "date": (evidence_row.event_date or evidence_row.published_at).isoformat()
                if (evidence_row.event_date or evidence_row.published_at)
                else None,
            }
        projects = account["items"]
        nested_needs = [need for project in projects for need in project["needs"]]
        direct_opportunity_projection = api_module.opportunity_projection(
            session,
            selected_need_ids={UUID(str(need["id"])) for need in nested_needs},
        )
        direct_evidence_details = {
            str(row["id"]): [
                {
                    "id": str(reference.get("id") or ""),
                    "assessment_current": reference.get("assessment_current") is True,
                    "source_id": reference.get("source_id"),
                }
                for reference in row.get("evidence", [])
            ]
            for row in direct_opportunity_projection
        }
        account_id = str(account["account"]["company_identity_id"])
        card_by_need = {str(card["id"]): card for card in cards}
        project_by_need = {}
        for project in project_projection["items"]:
            for need in project.get("needs", []):
                project_by_need[str(need["id"])] = (project, need)
        useful_need_ids = []
        amount_scopes: dict[str, int] = {}
        freshness_states: dict[str, int] = {}
        conflict_count = 0
        structured_brief_ids = []
        named_contact_ids = []
        generic_contact_ids = []
        source_verified_need_ids = []
        for need in nested_needs:
            need_id = str(need["id"])
            card = card_by_need.get(need_id, {})
            project, project_need = project_by_need.get(need_id, ({}, {}))
            brief = (
                _extract_brief(project_need)
                or _extract_brief(project)
                or _extract_brief(card)
                or _extract_brief(need)
            )
            shortlist = legacy_shortlist["assessments"].get(need_id, {})
            why = None
            action = None
            if brief:
                structured_brief_ids.append(need_id)
                why_value = brief.get("why_now")
                why = why_value.get("text") if isinstance(why_value, dict) else why_value
                action_value = brief.get("next_action")
                action = (
                    action_value.get("text") if isinstance(action_value, dict) else action_value
                )
                power = brief.get("power_need") or {}
                amount_class = power.get("amount_class") or "unknown"
                scope = power.get("scope") or "unknown"
                freshness = brief.get("freshness") or {}
                freshness_state = freshness.get("status") or "unknown"
                sources = brief.get("sources") or []
                contact = brief.get("best_contact") or {}
                route_kind = contact.get("route_kind") or contact.get("kind")
                if contact.get("contact") and (
                    contact.get("kind") == "named" or route_kind == "person_method"
                ):
                    named_contact_ids.append(need_id)
                elif contact.get("contact") and route_kind == "company_route":
                    generic_contact_ids.append(need_id)
                if why and action and sources:
                    current_sources = current_evidence_by_need.get(need_id, {})
                    why_sources = why_value.get("sources") if isinstance(why_value, dict) else None
                    action_source = (
                        action_value.get("source") if isinstance(action_value, dict) else None
                    )
                    references = list(why_sources or [])
                    if isinstance(action_source, dict):
                        references.append(action_source)
                    source_verified = bool(why_sources and references)
                    for source in references:
                        evidence_id = str(source.get("evidence_id") or source.get("id") or "")
                        current = current_sources.get(evidence_id)
                        if (
                            current is None
                            or source.get("url") != current["url"]
                            or (source.get("date") and source.get("date") != current.get("date"))
                        ):
                            source_verified = False
                            break
                    if source_verified:
                        source_verified_need_ids.append(need_id)
            else:
                why = shortlist.get("why_now")
                action = (
                    project_need.get("next_action")
                    or project.get("next_action")
                    or card.get("next_action")
                    or card.get("supported_action")
                )
                amount_class = "unknown"
                scope = project_need.get("activity_key") or "unknown/unclassified"
                freshness_state = "unknown/unclassified"
                source_ids = set(current_evidence_by_need.get(need_id, {}))
                assessment = legacy_shortlist["assessments"].get(need_id, {})
                why = assessment.get("why_now")
                action = assessment.get("next_step")
                source_verified = bool(
                    why and source_ids.intersection(assessment.get("evidence_refs", []))
                )
                if source_verified:
                    source_verified_need_ids.append(need_id)
            amount_key = f"{amount_class}|{scope}"
            amount_scopes[amount_key] = amount_scopes.get(amount_key, 0) + 1
            freshness_states[freshness_state] = freshness_states.get(freshness_state, 0) + 1
            if why and action and need_id in source_verified_need_ids:
                useful_need_ids.append(need_id)
            if card.get("conflict_state") not in {None, "", "Not assessed", "none", "NONE"}:
                conflict_count += 1
        company_contact_result = {
            "primary": primary_contacts,
            "lookalike": other_contacts,
        }
        jobs = list(session.scalars(select(Job)))
        logical_calls = list(session.scalars(select(LogicalCall)))
        planner_states = list(session.scalars(select(PlannerState)))
        question_rows = list(session.scalars(select(PursuitResearchQuestion)))
        question_receipts = []
        for question in question_rows:
            receipt = question.receipt or {}
            coverage = receipt.get("company_contact_research") or {}
            question_receipts.append(
                {
                    "need_id": str(question.need_id),
                    "project_id": str(question.project_id),
                    "category": question.category,
                    "status": question.status,
                    "error": (
                        question.receipt.get("error")
                        if isinstance(question.receipt.get("error"), str)
                        and re.fullmatch(r"[A-Za-z0-9_:-]{1,80}", question.receipt["error"])
                        else None
                    ),
                    "question_outcome": receipt.get("question_outcome"),
                    "source_check_dispositions": sorted(
                        str(check.get("disposition"))
                        for check in receipt.get("source_checks", [])
                        if check.get("disposition")
                    ),
                    "resulting_evidence_count": len(receipt.get("resulting_evidence_ids", [])),
                    "route_results": [
                        {
                            "kind": route.get("kind"),
                            "status": route.get("status"),
                            "reason": (
                                route.get("reason")
                                if isinstance(route.get("reason"), str)
                                and re.fullmatch(r"[A-Za-z0-9_ .:-]{1,100}", route["reason"])
                                else None
                            ),
                        }
                        for route in receipt.get("route_results", [])
                    ],
                    "company_contact_routes": [
                        {
                            "kind": route.get("kind"),
                            "status": route.get("status"),
                            "reason": (
                                route.get("reason")
                                if isinstance(route.get("reason"), str)
                                and re.fullmatch(r"[A-Za-z0-9_ .:-]{1,100}", route["reason"])
                                else None
                            ),
                        }
                        for route in receipt.get("route_results", [])
                        if route.get("kind") == "company_contact"
                    ],
                    "company_identity_ids": [
                        str(identity_id)
                        for identity_id in (
                            coverage.get("company_identity_ids", [])
                            if isinstance(coverage.get("company_identity_ids", []), list)
                            else []
                        )
                    ],
                    "retry_after_recorded": bool(
                        coverage.get("retry_after") or question.retry_after
                    ),
                    "cache_reuses": sum(
                        check.get("cache_reused") is True
                        for check in receipt.get("source_checks", [])
                    ),
                }
            )
        owner_managed_execution_rows = sum(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (CommercialPursuit, PursuitActivity, PursuitTask)
        )
        legacy_shortlist_details = []
        for need in nested_needs:
            need_id = str(need["id"])
            shortlist = legacy_shortlist["assessments"].get(need_id, {})
            source_verified = bool(
                shortlist.get("why_now")
                and set(current_evidence_by_need.get(need_id, {})).intersection(
                    shortlist.get("evidence_refs", [])
                )
            )
            eligible = bool(shortlist.get("eligible"))
            has_next_action = bool(shortlist.get("next_step"))
            has_why_now = bool(shortlist.get("why_now"))
            legacy_shortlist_details.append(
                {
                    "need_id": need_id,
                    "eligible": eligible,
                    "has_why_now": has_why_now,
                    "has_next_action": has_next_action,
                    "source_refs": len(shortlist.get("evidence_refs", [])),
                    "current_need_sources": len(current_evidence_by_need.get(need_id, {})),
                    "source_verified": source_verified,
                    "useful": eligible and has_why_now and has_next_action and source_verified,
                }
            )
        return {
            "account": account,
            "lookalike_account": other,
            "cards": cards,
            "project_projection": project_projection,
            "contacts": company_contact_result,
            "evidence": evidence,
            "amount_class_scope_counts": amount_scopes,
            "freshness_states": freshness_states,
            "conflict_count": conflict_count,
            "structured_brief_need_ids": structured_brief_ids,
            "named_contact_need_ids": named_contact_ids,
            "generic_contact_need_ids": generic_contact_ids,
            "source_verified_need_ids": source_verified_need_ids,
            "useful_need_ids": useful_need_ids,
            "contact_counts": {
                "named_contacts": sum(bool(contact.name) for contact in primary_contacts),
                "generic_methods": sum(
                    sum(
                        method.get("kind") in {"email", "phone", "website"}
                        for method in contact.methods
                    )
                    for contact in primary_contacts
                    if not contact.name
                ),
                "named_methods": sum(
                    sum(
                        method.get("kind") in {"email", "phone", "website"}
                        for method in contact.methods
                    )
                    for contact in primary_contacts
                    if contact.name
                ),
            },
            "legacy_shortlist_details": legacy_shortlist_details,
            "browse_evidence_details": browse_evidence_details,
            "direct_evidence_details": direct_evidence_details,
            "job_rows": jobs,
            "logical_calls": logical_calls,
            "question_receipts": question_receipts,
            "planner_states": planner_states,
            "owner_managed_execution_rows": owner_managed_execution_rows,
            "read_latency_ms": {
                "p50": round(statistics.median(latencies), 2),
                "p95": round(sorted(latencies)[-1], 2),
            },
            "canonical_account_id": account_id,
        }


def test_scheduled_research_persists_and_projects_replay_safely(phase2_db, monkeypatch):
    factory, worker, api_module, _scoped_engine, mode = phase2_db
    fixture_id, company_id, lookalike_id = _seed_fixture(factory)
    rebuild = saved_browse.rebuild(factory)
    assert rebuild["status"] == "published", rebuild
    # Only the two outbound HTTP transports are deterministic doubles. Parsing,
    # admission, persistence, ledger, planners, leases and projection are real.
    transport_calls = []
    retrieval_fails = {"enabled": False, "requests": 0}
    _install_http_transport(
        monkeypatch, outage=retrieval_fails, requests=transport_calls, mode=mode
    )

    import threading

    lanes = worker._worker_lane_specs(threading.Event(), {})
    lane_names = {name for name, _target, _args in lanes}
    assert "gridlens-planner-company-contacts" in lane_names
    assert "gridlens-planner-pursuit-questions" in lane_names
    started = time.perf_counter()
    from gridlens.domain.pursuit_research import fingerprint
    from gridlens.intelligence import autonomous_research
    from gridlens.intelligence.research_routing import routing_context, selected_sources

    def question_input_diagnostic(job_id):
        with factory() as session:
            job = session.get(Job, job_id)
            assert job is not None and job.kind == "pursuit_question"
            question = session.get(PursuitResearchQuestion, job.target_id)
            assert question is not None
            project = session.get(Project, question.project_id)
            assert project is not None
            category = question.category
            need_id = question.need_id
            expected = question.evidence_fingerprint
            context = dict(question.context)
            identity_key = project.identity_key
            route_fingerprint = routing_context(category, selected_sources(session, need_id))[
                "selected_source_fingerprint"
            ]
            from gridlens.intelligence.commercial_evaluation import evaluate_targets

            grouped_card = evaluate_targets(session, [str(need_id)], grouped=True).get(str(need_id))
        card = autonomous_research.current_card(need_id)
        current_input = card.get("input_hash") if card else None
        grouped_input = grouped_card.get("input_hash") if grouped_card else None
        planned_card = context.get("before") or {}
        planned_input = planned_card.get("input_hash")
        current_fingerprint = fingerprint([current_input, identity_key]) if current_input else None
        planned_fingerprint = fingerprint([planned_input, identity_key]) if planned_input else None
        return {
            "category": category,
            "stored_evidence_fingerprint_prefix": expected[:12],
            "planned_input_hash_prefix": str(planned_input or "")[:12],
            "current_input_hash_prefix": str(current_input or "")[:12],
            "grouped_input_hash_prefix": str(grouped_input or "")[:12],
            "changed_card_fields": sorted(
                key
                for key in set(planned_card) | set(card or {})
                if json.dumps(planned_card.get(key), sort_keys=True, default=str)
                != json.dumps((card or {}).get(key), sort_keys=True, default=str)
            ),
            "planned_input_matches_stored": planned_fingerprint == expected,
            "current_card_matches_stored": current_fingerprint == expected,
            "current_card_matches_planned": current_input == planned_input,
            "grouped_card_matches_planned": grouped_input == planned_input,
            "source_fingerprint_matches": (
                context.get("selected_source_fingerprint") == route_fingerprint
            ),
            "current_source_fingerprint_prefix": route_fingerprint[:12],
        }

    def retained_state_signature():
        from gridlens.persistence.models import Interpretation

        columns = {
            Project: ("id", "identity_key", "name", "location", "source_id", "external_id"),
            Observation: ("id", "content_hash", "source_id", "external_id"),
            Evidence: ("id", "observation_id", "content_hash", "url"),
            Interpretation: ("id", "observation_id", "content_hash", "status", "assessment"),
        }
        signature = {}
        with factory() as session:
            for model, names in columns.items():
                values = []
                for row in session.scalars(select(model)):
                    values.append({name: getattr(row, name) for name in names})
                values.sort(
                    key=lambda value: json.dumps(
                        value, sort_keys=True, default=str, separators=(",", ":")
                    )
                )
                canonical = json.dumps(values, sort_keys=True, default=str, separators=(",", ":"))
                signature[model.__tablename__] = {
                    "count": len(values),
                    "sha256": _digest(canonical),
                }
        return signature

    retained_before_planners = retained_state_signature()
    assert worker._run_planner("pursuit_questions", worker.plan_pursuit_questions)
    retained_after_question_planner = retained_state_signature()
    assert worker._run_planner("company_contacts", worker.plan_company_contact_jobs)
    retained_after_contact_planner = retained_state_signature()

    with factory() as session:
        scheduled = list(
            session.scalars(
                select(Job).where(
                    Job.kind.in_(["pursuit_question", "company_contact_discovery"]),
                    Job.status.in_(["queued", "running"]),
                )
            )
        )
        assert scheduled, "Scheduled planner invocation must persist durable worker jobs"
        assert any(job.kind == "company_contact_discovery" for job in scheduled)
        assert any(job.kind == "pursuit_question" for job in scheduled)
        scheduled_ids = [
            job.id
            for job in sorted(
                scheduled,
                key=lambda item: (item.kind != "pursuit_question", str(item.id)),
            )
        ]

    question_input_diagnostics = []
    scheduled_kinds = {str(job.id): job.kind for job in scheduled}
    for job_id in scheduled_ids:
        if scheduled_kinds[str(job_id)] == "pursuit_question":
            question_input_diagnostics.append(
                {"phase": "before_worker", **question_input_diagnostic(job_id)}
            )
        assert worker.run_one({}, job_ids=[job_id]) is True
        if scheduled_kinds[str(job_id)] == "pursuit_question":
            question_input_diagnostics.append(
                {"phase": "after_worker", **question_input_diagnostic(job_id)}
            )

    # Drain only the fixture's finite jobs. A repeated empty poll must be quiet.
    with factory() as session:
        remaining = list(
            session.scalars(
                select(Job).where(
                    Job.kind.in_(["pursuit_question", "company_contact_discovery"]),
                    Job.status.in_(["queued", "running"]),
                )
            )
        )
        for job in sorted(
            remaining,
            key=lambda item: (item.kind != "pursuit_question", str(item.id)),
        ):
            if job.kind == "pursuit_question":
                question_input_diagnostics.append(
                    {"phase": "before_worker", **question_input_diagnostic(job.id)}
                )
            assert worker.run_one({}, job_ids=[job.id]) is True
            if job.kind == "pursuit_question":
                question_input_diagnostics.append(
                    {"phase": "after_worker", **question_input_diagnostic(job.id)}
                )
    assert worker.run_one({}, job_ids=[]) is False
    # Canonical snapshots become visible only after the normal fenced rebuild.
    rebuilt = saved_browse.rebuild(factory)
    assert rebuilt["status"] == "published", rebuilt

    # One additional finite scheduled cycle checks the newly retained state.
    # It reuses existing planner/queue paths, and any resulting jobs are drained
    # by ID with the ordinary worker lease/fence implementation.
    def retained_counts():
        with factory() as session:
            models = (
                ("projects", Project),
                ("needs", PowerNeed),
                ("evidence", Evidence),
                ("jobs", Job),
                ("questions", PursuitResearchQuestion),
                ("logical_calls", LogicalCall),
            )
            counts = {
                name: session.scalar(select(func.count()).select_from(model)) or 0
                for name, model in models
            }
            job_ids = {str(job.id) for job in session.scalars(select(Job))}
            primary_contact_jobs = (
                session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.kind == "company_contact_discovery",
                        Job.target_id == company_id,
                    )
                )
                or 0
            )
        return counts, job_ids, primary_contact_jobs

    first_cycle_counts, first_cycle_job_ids, first_primary_contact_jobs = retained_counts()

    class NextScheduledCycle(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(hours=2)

    with monkeypatch.context() as clock:
        # Advance only the scheduler clock past its ordinary success interval;
        # project evidence and worker leases continue to use real timestamps.
        clock.setattr(worker, "datetime", NextScheduledCycle)
        assert worker._run_planner("pursuit_questions", worker.plan_pursuit_questions)
        assert worker._run_planner("company_contacts", worker.plan_company_contact_jobs)
    with factory() as session:
        second_cycle_jobs = list(
            session.scalars(
                select(Job).where(
                    Job.kind.in_(["pursuit_question", "company_contact_discovery"]),
                    Job.status.in_(["queued", "running"]),
                )
            )
        )
    bounded_cycle_job_ids = [
        job.id for job in second_cycle_jobs if str(job.id) not in first_cycle_job_ids
    ]
    retrieval_fails["enabled"] = True
    try:
        for job_id in bounded_cycle_job_ids:
            assert worker.run_one({}, job_ids=[job_id]) is True
    finally:
        retrieval_fails["enabled"] = False
    assert retrieval_fails["requests"] > 0, (
        "The bounded retry cycle must exercise the deterministic transport outage"
    )
    assert worker.run_one({}, job_ids=[]) is False
    second_cycle_counts, _second_cycle_job_ids, second_primary_contact_jobs = retained_counts()
    for table in ("projects", "needs", "evidence", "questions", "logical_calls"):
        assert second_cycle_counts[table] == first_cycle_counts[table], (
            f"An unchanged scheduled replay must not add {table}"
        )
    assert second_cycle_counts["jobs"] == first_cycle_counts["jobs"] + len(bounded_cycle_job_ids)
    assert first_primary_contact_jobs == 1
    assert second_primary_contact_jobs in {
        first_primary_contact_jobs,
        first_primary_contact_jobs + 1,
    }, "At most one bounded canonical retry may be created for the primary identity"
    rebuilt = saved_browse.rebuild(factory)
    assert rebuilt["status"] == "published", rebuilt

    before_replay = _capture_projection(factory, api_module, company_id, lookalike_id)
    assert before_replay["account"]["total"] == 3
    assert before_replay["account"]["account"]["project_count"] == 3
    assert before_replay["account"]["account"]["need_count"] == 4
    assert sorted(project["need_count"] for project in before_replay["account"]["items"]) == [
        1,
        1,
        2,
    ]
    assert before_replay["lookalike_account"]["total"] == 1
    assert before_replay["contacts"]["lookalike"] == []
    job_states = [
        (job.kind, job.status, json.loads(job.checkpoint or "{}"))
        for job in before_replay["job_rows"]
    ]
    assert before_replay["contacts"]["primary"], (
        "The fenced company contact worker should persist the exact-ID native RRC route. "
        f"Requests={transport_calls}; jobs={job_states}"
    )
    assert any(
        method.get("source_url")
        == "https://www.rrc.texas.gov/media/phase2/oil-and-gas-directory-11-08-26.xlsx"
        and method.get("value") == "5125550142"
        for contact in before_replay["contacts"]["primary"]
        for method in contact.methods
    ), "A later public-site outage must preserve the previously accepted native route"
    assert before_replay["owner_managed_execution_rows"] == 0
    assert any(item["useful"] for item in before_replay["legacy_shortlist_details"]), (
        "The matched synthetic fixture must yield at least one existing source-backed "
        "WhyNow plus justified next step before Phase 2 is compared."
    )
    assert any(not path.endswith("/robots.txt") for path in transport_calls), (
        "The company contact worker should issue a page GET after the synthetic robots allow: "
        f"{[(job.kind, job.status, json.loads(job.checkpoint or '{}')) for job in scheduled]}"
    )
    if mode == "candidate":
        primary_contact_jobs = [
            job
            for job in before_replay["job_rows"]
            if job.kind == "company_contact_discovery" and str(job.target_id) == str(company_id)
        ]
        assert len(primary_contact_jobs) == second_primary_contact_jobs, (
            "The persisted projection and second scheduled cycle should agree on "
            "canonical company job history"
        )
        p5_source_url = "https://www.rrc.texas.gov/media/phase2/oil-and-gas-directory-11-08-26.xlsx"
        primary_p5_methods = [
            method
            for contact in before_replay["contacts"]["primary"]
            for method in contact.methods
            if method.get("source_url") == p5_source_url
        ]
        assert any(
            method.get("kind") == "phone" and method.get("value") == "5125550142"
            for method in primary_p5_methods
        ), "Primary call route must come from the exact-number native RRC P5 row"
        buyer_questions = [
            item for item in before_replay["question_receipts"] if item["category"] == "buyer"
        ]
        buyer_handoffs = [
            item
            for item in buyer_questions
            if any(route["status"] == "DEFERRED" for route in item["company_contact_routes"])
        ]
        assert all(
            str(company_id) in item["company_identity_ids"] and item["retry_after_recorded"]
            for item in buyer_handoffs
        ), "Any persisted buyer deferral must reference the current canonical company pass"
        assert not any(
            item["error"] == "input_changed_before_research"
            for item in before_replay["question_receipts"]
        ), "Scheduled question workers must not all self-invalidate against their planned card"
        blocked_questions = [
            item
            for item in before_replay["question_receipts"]
            if item["question_outcome"] == "BLOCKED"
        ]
        assert blocked_questions, "Disabled public providers should leave an honest blocked gap"
        assert all(
            any(
                route["kind"] == "retained" and route["status"] == "CHECKED"
                for route in item["route_results"]
            )
            and any(
                route["kind"] == "discovery"
                and route["status"] == "UNAVAILABLE"
                and route["reason"] == "CONTRACT_DISABLED"
                for route in item["route_results"]
            )
            for item in blocked_questions
        ), "Blocked questions must show retained evidence checked and disabled discovery honestly"
        assert any(
            item["resulting_evidence_count"]
            or item["source_check_dispositions"]
            or any(
                route["status"] not in {"NOT_REACHED", "PLANNED", "SKIPPED"}
                for route in item["route_results"]
            )
            for item in before_replay["question_receipts"]
        ), "At least one scheduled question worker must reach a real route/check outcome"
        assert not any(
            call.task_type == "FIRECRAWL_SEARCH_V2" for call in before_replay["logical_calls"]
        ), "Company-contact handoff must precede any duplicate paid Firecrawl search"

    # Exact-replay plans reuse current queue/evidence and do not create another
    # physical account/site, finding, or owner-managed action.
    with factory() as session:
        first_counts = {
            table: session.scalar(select(func.count()).select_from(model)) or 0
            for table, model in (
                ("project", Project),
                ("power_need", PowerNeed),
                ("evidence", Evidence),
                ("job", Job),
            )
        }
    with factory.begin() as session:
        from gridlens.intelligence.company_contact_discovery import plan_company_contact_jobs

        assert plan_company_contact_jobs(session, limit=10) == 0
    after_replay = _capture_projection(factory, api_module, company_id, lookalike_id)
    with factory() as session:
        second_counts = {
            table: session.scalar(select(func.count()).select_from(model)) or 0
            for table, model in (
                ("project", Project),
                ("power_need", PowerNeed),
                ("evidence", Evidence),
                ("job", Job),
            )
        }
    assert second_counts == first_counts
    assert after_replay["canonical_account_id"] == before_replay["canonical_account_id"]
    assert after_replay["account"]["account"]["project_count"] == 3
    assert after_replay["account"]["account"]["need_count"] == 4
    assert after_replay["owner_managed_execution_rows"] == 0

    if mode == "candidate":
        assert before_replay["structured_brief_need_ids"], (
            "Candidate must expose a qualified optional commercial_brief"
        )
        for card in before_replay["cards"]:
            brief = _extract_brief(card)
            if brief:
                assert {
                    "version",
                    "why_now",
                    "power_need",
                    "best_contact",
                    "next_action",
                    "freshness",
                    "limitations",
                    "sources",
                } <= brief.keys()
                assert brief["why_now"].get("text")
                assert brief["why_now"].get("scope")
                assert brief["why_now"].get("sources")
                assert brief["power_need"].get("amount_class")
                assert brief["power_need"].get("scope")
                assert brief["next_action"].get("text")
        campus = next(
            need
            for project in before_replay["account"]["items"]
            if "Campus C" in project["name"]
            for need in project["needs"]
        )
        campus_card = next(
            card for card in before_replay["cards"] if str(card["id"]) == str(campus["id"])
        )
        campus_brief = _extract_brief(campus_card) or _extract_brief(campus)
        assert campus_brief
        campus_power = campus_brief["power_need"]
        assert campus_power.get("amount_class") == "unknown"
        assert "rental" not in str(campus_power.get("scope", "")).lower()
        assert "40" not in str(campus_power.get("value", ""))

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    receipt_path = os.environ.get("PHASE2_RECEIPT_PATH")
    if receipt_path:
        import importlib

        imported_root = Path(
            os.environ.get(
                "PHASE2_EXPECTED_SOURCE_ROOT", Path(gridlens.__file__).resolve().parents[1]
            )
        ).resolve()
        source_modules = {}
        optional_baseline_modules = {
            "gridlens.intelligence.company_contact_attribution",
            "gridlens.domain.commercial_brief",
            "gridlens.ingestion.adapters.public_site_policy",
        }
        for module_name in (
            "gridlens.api.app",
            "gridlens.jobs.worker",
            "gridlens.domain.commercial_brief",
            "gridlens.domain.pursuit_research",
            "gridlens.intelligence.autonomous_research",
            "gridlens.intelligence.buying_chain",
            "gridlens.intelligence.commercial_evaluation",
            "gridlens.intelligence.company_contact_attribution",
            "gridlens.intelligence.company_contact_discovery",
            "gridlens.intelligence.customer_accounts",
            "gridlens.intelligence.customer_results",
            "gridlens.intelligence.pursuit_questions",
            "gridlens.intelligence.project_results",
            "gridlens.intelligence.research_routing",
            "gridlens.intelligence.saved_browse",
            "gridlens.ingestion.adapters.buying_chain_public",
            "gridlens.ingestion.adapters.public_site_policy",
            "gridlens.ingestion.adapters.rrc_operator_directory",
        ):
            if mode == "baseline" and module_name in optional_baseline_modules:
                if importlib.util.find_spec(module_name) is None:
                    continue
            module = importlib.import_module(module_name)
            module_path = Path(module.__file__).resolve()
            assert module_path.is_relative_to(imported_root), (
                f"Imported {module_name} from outside selected source root: {module_path}"
            )
            source_modules[module_name] = {
                "path": str(module_path),
                "sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
            }
        snapshot = {
            "mode": mode,
            "fixture_id": fixture_id,
            "data_kind": "SYNTHETIC fixture only",
            "source_commit": os.environ.get("PHASE2_SOURCE_COMMIT", "unavailable-local-test"),
            "imported_source_root": str(Path(gridlens.__file__).resolve().parents[1]),
            "imported_module": str(Path(gridlens.__file__).resolve()),
            "imported_module_sha256": hashlib.sha256(
                Path(gridlens.__file__).read_bytes()
            ).hexdigest(),
            "source_modules": source_modules,
            "entities": {
                "canonical_account_ids": [
                    str(before_replay["account"]["account"]["company_identity_id"]),
                    str(before_replay["lookalike_account"]["account"]["company_identity_id"]),
                ],
                "physical_project_ids": [
                    str(project["id"]) for project in before_replay["account"]["items"]
                ]
                + [str(project["id"]) for project in before_replay["lookalike_account"]["items"]],
                "need_ids": [
                    str(need["id"])
                    for result in (before_replay["account"], before_replay["lookalike_account"])
                    for project in result["items"]
                    for need in project["needs"]
                ],
            },
            "commercial": {
                "useful_need_ids": before_replay["useful_need_ids"],
                "amount_class_scope_counts": before_replay["amount_class_scope_counts"],
                "named_contact_need_ids": before_replay["named_contact_need_ids"],
                "generic_contact_need_ids": before_replay["generic_contact_need_ids"],
                "freshness_states": before_replay["freshness_states"],
                "conflict_count": before_replay["conflict_count"],
                "structured_brief_need_ids": before_replay["structured_brief_need_ids"],
                "fixture_input_sha256": fixture_id.removeprefix("phase2-cross-lane-v3-"),
                "evaluator_sha256": _digest(
                    Path(__file__).read_bytes().decode("utf-8")
                    + Path(__file__)
                    .parents[3]
                    .joinpath("scripts", "phase2_metrics.py")
                    .read_bytes()
                    .decode("utf-8")
                ),
                "source_verified_need_ids": before_replay["source_verified_need_ids"],
                "legacy_shortlist_details": before_replay["legacy_shortlist_details"],
                "browse_evidence_details": before_replay["browse_evidence_details"],
                "direct_evidence_details": before_replay["direct_evidence_details"],
                "contact_counts": before_replay["contact_counts"],
                "question_receipts": before_replay["question_receipts"],
            },
            "pipeline": {
                "scheduled_jobs": len(scheduled_ids),
                "second_scheduled_cycle": {
                    "processed_new_job_count": len(bounded_cycle_job_ids),
                    "simulated_outage_requests": retrieval_fails["requests"],
                    "counts_before": first_cycle_counts,
                    "counts_after": second_cycle_counts,
                    "new_job_count": second_cycle_counts["jobs"] - first_cycle_counts["jobs"],
                    "primary_contact_jobs_before": first_primary_contact_jobs,
                    "primary_contact_jobs_after": second_primary_contact_jobs,
                    "retained_findings_unchanged": all(
                        second_cycle_counts[name] == first_cycle_counts[name]
                        for name in ("projects", "needs", "evidence", "questions")
                    ),
                    "provider_ledger_unchanged": (
                        second_cycle_counts["logical_calls"] == first_cycle_counts["logical_calls"]
                    ),
                },
                "question_input_diagnostics": question_input_diagnostics,
                "retained_state_digests": {
                    "before_planners": retained_before_planners,
                    "after_question_planner": retained_after_question_planner,
                    "after_contact_planner": retained_after_contact_planner,
                    "question_planner_changed_source_rows": (
                        retained_after_question_planner != retained_before_planners
                    ),
                    "contact_planner_changed_source_rows": (
                        retained_after_contact_planner != retained_after_question_planner
                    ),
                },
                "successful_jobs": sum(
                    job.status == "succeeded" for job in before_replay["job_rows"]
                ),
                "failed_jobs": sum(job.status == "failed" for job in before_replay["job_rows"]),
                "provider_logical_requests": len(before_replay["logical_calls"]),
                "provider_cache_reuses": sum(
                    receipt["cache_reuses"] for receipt in before_replay["question_receipts"]
                ),
                "buyer_handoffs": sum(
                    route.get("status") == "DEFERRED"
                    for receipt in before_replay["question_receipts"]
                    for route in receipt["company_contact_routes"]
                ),
                "mock_transport_requests": len(transport_calls),
                "mock_robots_requests": sum(
                    path.endswith("/robots.txt") for path in transport_calls
                ),
                "mock_target_requests": sum(
                    not path.endswith("/robots.txt") for path in transport_calls
                ),
                "mock_transport_urls": transport_calls,
                "synthetic_mock_cost_usd": "0.000000",
                "real_provider_cost": "UNKNOWN / unverified",
                "elapsed_ms": elapsed_ms,
                "read_latency_ms": before_replay["read_latency_ms"],
                "recovery_completed": after_replay["account"]["account"]["need_count"] == 4
                and second_counts == first_counts,
            },
        }
        Path(receipt_path).parent.mkdir(parents=True, exist_ok=True)
        Path(receipt_path).write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
