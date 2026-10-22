"""Synthetic F17 adapter records traverse the ordinary fenced persistence path."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters import retained_document
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.retained_document import SOURCES
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import _need_admission_basis_is_current
from gridlens.intelligence import buying_chain as buying_chain_module
from gridlens.intelligence.buying_chain import BuyingChainClaim, buying_chain_view
from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

IMPORT_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_retained_document.py"
IMPORT_SPEC = importlib.util.spec_from_file_location("retained_document_import_cli", IMPORT_SCRIPT)
assert IMPORT_SPEC is not None and IMPORT_SPEC.loader is not None
import_retained_document = importlib.util.module_from_spec(IMPORT_SPEC)
IMPORT_SPEC.loader.exec_module(import_retained_document)


@pytest.fixture
def retained_db(monkeypatch):
    test_url = make_url(settings.test_database_url)
    app_url = make_url(settings.database_url)
    assert test_url.database and test_url.database.endswith("_test")
    assert (test_url.host, test_url.port, test_url.database) != (
        app_url.host,
        app_url.port,
        app_url.database,
    )
    schema = "retained_f17_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    definitions = {item["id"]: item for item in load_registry()}
    synthetic_text = {
        "f17-stack-city-claim": (
            "SVY02A / Memorex Junction data center at 1200 Memorex Drive, Santa Clara, CA. "
            "1220 Santa Clara Propco, LLC is the current owner of SVY02A at 1200 Memorex Drive, "
            "Santa Clara. "
            "Claim dated June 24, 2024 reports a cap of 18 MVA until at least 2028; "
            "earlier available schedule was 28 MVA in 2026 and 31 MVA by 2027."
        ),
        "f17-stack-cec-filing": (
            "SVY02A / Memorex Junction data center at 1200 Memorex Drive, Santa Clara, CA. "
            "STACK's dated CEC submission reports the facility is vastly underserved. "
            "It attaches a September 2021 draft agreement, Draft rev 0 - 9/30/2021, naming "
            "1220 Santa Clara Propco, LLC "
            '("Customer"). Table E1 - Available Capacity '
            "Schedule Capacity Paid Development (MVA) Fee Payment Capacity 28 10 20 31 10 30."
        ),
        "f17-crusoe-impact": (
            "Abilene Stargate campus near Abilene, Texas. The Abilene Stargate campus exemplifies "
            "Crusoe's energy-first, vertically integrated model. In the Abilene Stargate campus, "
            "we use natural gas turbines to provide temporary bridge power while grid upgrades "
            "catch up."
        ),
    }
    original_policies = {key: SOURCES[key] for key in SOURCES}
    with factory.begin() as session:
        for source_id, definition in definitions.items():
            if source_id not in SOURCES:
                continue
            source_values = {
                key: value for key, value in definition.items() if key in Source.__table__.columns
            }
            source_values.update(enabled=False, registry_enabled=False)
            session.add(Source(**source_values))
    policy_hashes = {}
    for source_id, policy in SOURCES.items():
        body = f"%PDF-synthetic-{source_id}".encode()
        policy_hashes[source_id] = hashlib.sha256(body).hexdigest()
        monkeypatch.setitem(
            SOURCES,
            source_id,
            {
                **policy,
                "path": f"synthetic-test-only-{source_id}.pdf",
                "sha256": policy_hashes[source_id],
                "spans": ((1, 1),),
            },
        )
    # A deterministic page reader selects its synthetic text from the exact
    # source body bytes passed to PdfReader.
    monkeypatch.setattr(
        retained_document,
        "PdfReader",
        lambda stream: _SyntheticReader(stream.read(), synthetic_text),
    )
    monkeypatch.setattr(import_retained_document, "SessionLocal", factory)
    monkeypatch.setattr(import_retained_document, "sync_registry", lambda: [])
    monkeypatch.setattr(settings, "database_url", settings.test_database_url)
    monkeypatch.setattr(
        buying_chain_module,
        "retrieve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network retrieval")),
    )
    monkeypatch.setattr(
        buying_chain_module,
        "extract_organizations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generic organization extraction")
        ),
    )
    monkeypatch.setattr(
        buying_chain_module,
        "extract_people",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generic person extraction")
        ),
    )
    yield factory, definitions, synthetic_text
    monkeypatch.setattr(retained_document, "SOURCES", original_policies)
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


class _SyntheticReader:
    def __init__(self, body: bytes, sources: dict[str, str]):
        source_id = body.decode().removeprefix("%PDF-synthetic-").split("|", 1)[0]
        self.pages = [type("Page", (), {"extract_text": lambda _self: sources[source_id]})()]


def _retained_state_snapshot(session):
    def digest(value):
        encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def rows(model, fields):
        records = session.scalars(select(model).order_by(model.id)).all()
        return [tuple(getattr(record, field) for field in fields) for record in records]

    need_rows = [
        {column.name: getattr(need, column.name) for column in PowerNeed.__table__.columns}
        for need in session.scalars(select(PowerNeed).order_by(PowerNeed.id)).all()
    ]
    project_ids = session.scalars(select(Project.id).order_by(Project.id)).all()
    chain_views = [
        buying_chain_view(session, project_id)["candidates"] for project_id in project_ids
    ]
    counts = {
        model.__tablename__: session.scalar(select(func.count()).select_from(model))
        for model in (
            Observation,
            Evidence,
            Project,
            PowerNeed,
            NeedObservation,
            BuyingChainEvidence,
            BuyingChainClaim,
            BuyingChainIdentityLink,
        )
    }
    return {
        "counts": counts,
        "need_rows": need_rows,
        "chain_evidence": digest(
            rows(BuyingChainEvidence, ("id", "project_id", "retained_evidence_id", "content_hash"))
        ),
        "claims": digest(rows(BuyingChainClaim, ("id", "project_id", "fingerprint", "citations"))),
        "identity_links": digest(
            rows(
                BuyingChainIdentityLink,
                ("id", "claim_id", "source_evidence_id", "source_version_hash", "state"),
            )
        ),
        "card_candidates": digest(chain_views),
    }


def test_f17_role_extraction_rejects_wrong_retained_body_hash():
    source_id = "f17-stack-city-claim"
    policy = SOURCES[source_id]
    text_body = (
        "SVY02A / Memorex Junction data center at 1200 Memorex Drive, Santa Clara, CA. "
        "1220 Santa Clara Propco, LLC is the current owner of SVY02A at 1200 Memorex Drive, "
        "Santa Clara."
    )
    doc = PublicDocument(
        url=policy["url"],
        title="Synthetic reviewed city claim",
        text=text_body,
        extraction_location="PDF pp. 14-18",
        retained_version="accepted-evidence-hash",
        structured=(
            {
                "f17_retained": {
                    "source_id": source_id,
                    "evidence_content_hash": "accepted-evidence-hash",
                    "project_name": "SVY02A / Memorex Junction data center",
                    "project_location": policy["location"],
                    "retained_document": {
                        "path": policy["path"],
                        "sha256": "wrong-original-body-hash",
                        "source_site": policy["location"],
                        "project_name": "SVY02A / Memorex Junction data center",
                        "reviewed_spans": ["PDF pp. 14-18"],
                    },
                }
            },
        ),
    )
    assert extract_retained_permit_organizations(doc, source_id) == []


def test_three_retained_documents_project_two_sites_and_replay_idempotently(retained_db, tmp_path):
    factory, definitions, _synthetic_text = retained_db
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for source_id, policy in SOURCES.items():
        (source_root / policy["path"]).write_bytes(f"%PDF-synthetic-{source_id}".encode())

    first_pass = []
    for source_id in SOURCES:
        first_pass.append(import_retained_document.run(source_id, source_root))
    with factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 3
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 2
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 3
        projects = {
            (project.name, project.location) for project in session.scalars(select(Project)).all()
        }
        assert projects == {
            ("SVY02A / Memorex Junction data center", "1200 Memorex Drive, Santa Clara, CA"),
            ("Abilene Stargate campus", "near Abilene, Texas"),
        }
        needs = session.scalars(select(PowerNeed).order_by(PowerNeed.activity_key)).all()
        assert {need.activity_key for need in needs} == {"utility-service", "bridge-power"}
        assert all(
            need.required_mw is None
            and need.start_window is None
            and need.duration is None
            and need.supply == "Unknown"
            for need in needs
        )
        evidence = session.scalars(select(Evidence)).all()
        assert all(item.extraction_location.startswith("PDF pp.") for item in evidence)
        assert all(item.provenance["retained_document"]["reviewed_spans"] for item in evidence)
        assert {item.url for item in evidence} == {policy["url"] for policy in SOURCES.values()}
        assert all(item.event_date is not None for item in evidence)
        assert all(
            item.published_at is None
            for item in evidence
            if item.url == SOURCES["f17-stack-city-claim"]["url"]
            or item.url == SOURCES["f17-crusoe-impact"]["url"]
        )
        needs_by_activity = {need.activity_key: need for need in needs}
        assert "not an open purchase" in needs_by_activity["bridge-power"].rationale
        claim_evidence = next(
            item for item in evidence if item.url == SOURCES["f17-stack-city-claim"]["url"]
        )
        assert "18 MVA" in claim_evidence.abstract
        assert "28 MV A" in claim_evidence.abstract or "28 MVA" in claim_evidence.abstract
        stack_project = next(
            p
            for p in session.scalars(select(Project))
            if p.name == "SVY02A / Memorex Junction data center"
        )
        stack_claims = [
            claim
            for claim in buying_chain_view(session, stack_project.id)["candidates"]
            if claim["organization"] == "1220 Santa Clara Propco, LLC"
        ]
        assert {claim["category"] for claim in stack_claims} == {"owner_developer", "unknown"}
        assert all(claim["evidence"] for claim in stack_claims)
        owner_claim = next(
            claim for claim in stack_claims if claim["category"] == "owner_developer"
        )
        draft_claim = next(claim for claim in stack_claims if claim["category"] == "unknown")
        assert "not a legal finding" in owner_claim["reason"]
        assert "draft designation" in draft_claim["reason"]
        crusoe_project = next(
            p for p in session.scalars(select(Project)) if p.name == "Abilene Stargate campus"
        )
        crusoe_view = buying_chain_view(session, crusoe_project.id)
        crusoe = [claim for claim in crusoe_view["candidates"] if claim["organization"] == "Crusoe"]
        assert len(crusoe) == 1 and crusoe[0]["category"] == "asset_operator"
        assert "not an open purchase" in crusoe[0]["reason"]
        assert len(crusoe[0]["evidence"]) == 2
        assert all(not claim["person_name"] for claim in [*stack_claims, *crusoe])
        initial_state = _retained_state_snapshot(session)

    with factory() as session:
        before = {
            (claim.project_id, claim.fingerprint)
            for claim in session.scalars(select(BuyingChainClaim)).all()
        }
        assert len(before) == 3

    for source_id in SOURCES:
        import_retained_document.run(source_id, source_root)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 3
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 2
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 3
        assert _retained_state_snapshot(session) == initial_state
        after = {
            (claim.project_id, claim.fingerprint)
            for claim in session.scalars(select(BuyingChainClaim)).all()
        }
        assert after == before
        assert session.scalar(select(func.count()).select_from(BuyingChainClaim)) == 3
        assert (
            session.scalar(select(func.count()).select_from(Job).where(Job.status == "succeeded"))
            == 6
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Interpretation)
                .where(Interpretation.status != "accepted")
            )
            == 0
        )


@pytest.mark.parametrize(
    ("first_source", "second_source"),
    [
        ("f17-stack-city-claim", "f17-stack-cec-filing"),
        ("f17-stack-cec-filing", "f17-stack-city-claim"),
    ],
)
def test_stack_need_basis_and_digest_stay_stable_in_either_source_order(
    retained_db, tmp_path, first_source, second_source
):
    factory, _definitions, _synthetic_text = retained_db
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for source_id in (first_source, second_source):
        policy = SOURCES[source_id]
        (source_root / policy["path"]).write_bytes(f"%PDF-synthetic-{source_id}".encode())

    import_retained_document.run(first_source, source_root)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None
        first_basis = need.admission_basis
        assert first_basis["source_id"] == first_source
        project = session.get(Project, need.project_id)
        assert project is not None and _need_admission_basis_is_current(session, need, project)

    import_retained_document.run(second_source, source_root)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None and need.admission_basis == first_basis
        before_replay = _retained_state_snapshot(session)

    import_retained_document.run(first_source, source_root)
    with factory() as session:
        assert _retained_state_snapshot(session) == before_replay
    import_retained_document.run(second_source, source_root)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None and need.admission_basis == first_basis
        after_replay = _retained_state_snapshot(session)
        changed_need_fields = [
            {
                key: (previous[key], current[key])
                for key in previous
                if previous[key] != current[key]
            }
            for previous, current in zip(
                before_replay["need_rows"], after_replay["need_rows"], strict=True
            )
        ]
        assert after_replay["need_rows"] == before_replay["need_rows"], changed_need_fields
        assert after_replay == before_replay


@pytest.mark.parametrize("invalid_basis", [None, {"source_id": "stale-policy"}])
def test_next_retained_source_repairs_absent_or_stale_need_basis(
    retained_db, tmp_path, invalid_basis
):
    factory, _definitions, _synthetic_text = retained_db
    first_source = "f17-stack-cec-filing"
    repair_source = "f17-stack-city-claim"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for source_id in (first_source, repair_source):
        policy = SOURCES[source_id]
        (source_root / policy["path"]).write_bytes(f"%PDF-synthetic-{source_id}".encode())

    import_retained_document.run(first_source, source_root)
    with factory.begin() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None
        need.admission_basis = invalid_basis

    import_retained_document.run(repair_source, source_root)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None
        assert need.admission_basis["source_id"] == repair_source
        assert (
            need.admission_basis["evidence_hash"]
            == hashlib.sha256(f"%PDF-synthetic-{repair_source}".encode()).hexdigest()
        )


def test_reopened_need_uses_new_retained_source_basis(retained_db, tmp_path):
    factory, _definitions, _synthetic_text = retained_db
    first_source = "f17-stack-cec-filing"
    reopen_source = "f17-stack-city-claim"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for source_id in (first_source, reopen_source):
        policy = SOURCES[source_id]
        (source_root / policy["path"]).write_bytes(f"%PDF-synthetic-{source_id}".encode())

    import_retained_document.run(first_source, source_root)
    with factory.begin() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None
        need.active = False

    import_retained_document.run(reopen_source, source_root)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None and need.active
        assert need.admission_basis["source_id"] == reopen_source
        assert "June 24, 2024 claim" in need.rationale


def test_failed_import_rolls_back_source_records_and_leaves_failed_receipt(
    retained_db, tmp_path, monkeypatch
):
    factory, _definitions, _synthetic_text = retained_db
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for source_id, policy in SOURCES.items():
        (source_root / policy["path"]).write_bytes(f"%PDF-synthetic-{source_id}".encode())

    import_retained_document.run("f17-stack-cec-filing", source_root)
    with factory() as session:
        accepted_hashes = {item.content_hash for item in session.scalars(select(Evidence)).all()}
        accepted_need_rationale = session.scalar(select(PowerNeed.rationale))
        assert len(accepted_hashes) == 1

    # Changed bytes fail closed before any import job or canonical mutation.
    city_path = source_root / SOURCES["f17-stack-city-claim"]["path"]
    city_path.write_bytes(city_path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        import_retained_document.run("f17-stack-city-claim", source_root)
    city_path.write_bytes(b"%PDF-synthetic-f17-stack-city-claim")

    original = import_retained_document.process_records

    def process_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure after canonical ingestion")

    monkeypatch.setattr(import_retained_document, "process_records", process_then_fail)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        import_retained_document.run("f17-stack-city-claim", source_root)

    with factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert {
            item.content_hash for item in session.scalars(select(Evidence)).all()
        } == accepted_hashes
        assert session.scalar(select(PowerNeed.rationale)) == accepted_need_rationale
        failed = session.scalars(select(Job).where(Job.status == "failed")).all()
        assert len(failed) == 1
        assert failed[0].lease_owner is None and failed[0].lease_until is None

        failed_job_id = failed[0].id
        failed_job_worker = "stale-worker"
        failed_job_fence = failed[0].fence
        # A newer lease owns the row; the stale completion token cannot finish it.
        failed[0].status = "running"
        failed[0].lease_owner = "newer-worker"
        failed[0].fence += 1
        failed[0].lease_until = datetime.now(UTC) + timedelta(minutes=5)

    with factory.begin() as session:
        with pytest.raises(RuntimeError, match="fence lost"):
            assert_fence(session, failed_job_id, str(failed_job_worker), failed_job_fence)
        current = session.get(Job, failed_job_id)
        assert current and current.status == "running"
        assert current.lease_owner == "newer-worker"


def test_reviewed_synthetic_hash_update_retains_old_version_and_relinks_current_need(
    retained_db, tmp_path, monkeypatch
):
    factory, _definitions, _synthetic_text = retained_db
    source_id = "f17-stack-city-claim"
    policy = SOURCES[source_id]
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_path = source_root / policy["path"]
    original_body = f"%PDF-synthetic-{source_id}".encode()
    source_path.write_bytes(original_body)
    import_retained_document.run(source_id, source_root)
    original_hash = hashlib.sha256(original_body).hexdigest()

    revised_body = f"%PDF-synthetic-{source_id}|reviewed-v2".encode()
    revised_hash = hashlib.sha256(revised_body).hexdigest()
    source_path.write_bytes(revised_body)
    monkeypatch.setitem(SOURCES, source_id, {**policy, "sha256": revised_hash})
    import_retained_document.run(source_id, source_root)

    with factory() as session:
        observation = session.scalar(select(Observation).where(Observation.source_id == source_id))
        assert observation is not None
        versions = session.scalars(
            select(Evidence).where(Evidence.observation_id == observation.id)
        ).all()
        assert {item.content_hash for item in versions} == {original_hash, revised_hash}
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert interpretation is not None and interpretation.status == "accepted"
        assert interpretation.assessment["evidence_hash"] == revised_hash
        projects = session.scalars(select(Project)).all()
        needs = session.scalars(select(PowerNeed)).all()
        assert len(projects) == len(needs) == 1
        assert needs[0].project_id == projects[0].id
        links = session.scalars(
            select(NeedObservation).where(NeedObservation.observation_id == observation.id)
        ).all()
        assert len(links) == 1 and links[0].need_id == needs[0].id
        assert needs[0].admission_basis["source_id"] == source_id
        assert needs[0].admission_basis["evidence_hash"] == revised_hash
