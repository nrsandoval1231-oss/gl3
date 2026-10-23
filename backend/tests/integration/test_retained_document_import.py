"""Synthetic F17 adapter records traverse the ordinary fenced persistence path."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor
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
from gridlens.ingestion.service import (
    _need_admission_basis_is_current,
    process_records,
)
from gridlens.intelligence import buying_chain as buying_chain_module
from gridlens.intelligence.buying_chain import BuyingChainClaim, buying_chain_view
from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations
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
        "test-retained-tx-a": (
            "TX Shared Compute campus site address is 500 Synthetic Drive, Austin, TX. "
            "The project is planning a new utility service."
        ),
        "test-retained-tx-b": (
            "TX Shared Compute campus site address is 500 Synthetic Drive, Austin, TX. "
            "The project is planning a new utility service."
        ),
    }
    original_policies = {key: SOURCES[key] for key in SOURCES}
    synthetic_policies = {
        source_id: {
            "path": f"{source_id}.pdf",
            "sha256": hashlib.sha256(f"%PDF-synthetic-{source_id}".encode()).hexdigest(),
            "url": f"https://example.test/retained/{source_id}.pdf",
            "publisher": f"Synthetic test publisher {source_id}",
            "publication_date": "2026-10-20",
            "event_date": "2026-10-20",
            "event_date_label": "Synthetic test event date",
            "spans": ((1, 1),),
            "site_cue": "500 Synthetic Drive",
            "activity": "utility-service",
            "project_cue": "TX Shared Compute",
            "project_suffix": "campus",
            "location": "500 Synthetic Drive, Austin, TX",
            "location_cues": ("500 Synthetic Drive", "Austin", "TX"),
            "location_pattern": r"500 Synthetic Drive, Austin, TX",
            "rationale_kind": "stack_claim",
            "required_terms": ("planning", "new utility service"),
        }
        for source_id in ("test-retained-tx-a", "test-retained-tx-b")
    }
    for source_id, policy in synthetic_policies.items():
        monkeypatch.setitem(
            SOURCES,
            source_id,
            {
                **policy,
                "project_cue": "TX Shared Compute",
                "site_cue": "500 Synthetic Drive",
                "location_cues": ("500 Synthetic Drive", "Austin", "TX"),
            },
        )
    with factory.begin() as session:
        for source_id, definition in definitions.items():
            if source_id not in SOURCES:
                continue
            source_values = {
                key: value for key, value in definition.items() if key in Source.__table__.columns
            }
            source_values.update(enabled=False, registry_enabled=False)
            session.add(Source(**source_values))
        for source_id, policy in synthetic_policies.items():
            policy = SOURCES[source_id]
            session.add(
                Source(
                    id=source_id,
                    publisher=policy["publisher"],
                    endpoint=policy["url"],
                    family="retained-public-document",
                    geography="Texas",
                    industries=["data centers"],
                    retrieval_method="retained-document",
                    cadence_hours=24,
                    enabled=False,
                    registry_enabled=False,
                    health={},
                )
            )
    policy_hashes = {}
    for source_id, policy in list(SOURCES.items()):
        body = f"%PDF-synthetic-{source_id}".encode()
        policy_hashes[source_id] = hashlib.sha256(body).hexdigest()
        if source_id in original_policies:
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
    for source_id in synthetic_policies:
        synthetic_policies[source_id] = SOURCES[source_id]
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


def test_concurrent_retained_job_admission_serializes_on_source_row(retained_db):
    factory, _definitions, _synthetic_text = retained_db
    source_id = "f17-stack-city-claim"
    first_admitted = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_finished = threading.Event()
    now = datetime.now(UTC)

    def first() -> None:
        with factory.begin() as session:
            import_retained_document._admit_retained_job(
                session, source_id, uuid4(), "first-importer", now
            )
            session.flush()
            first_admitted.set()
            assert release_first.wait(10)

    def second() -> str:
        second_started.set()
        try:
            with factory.begin() as session:
                import_retained_document._admit_retained_job(
                    session, source_id, uuid4(), "second-importer", now
                )
                session.flush()
        except ValueError as exc:
            second_finished.set()
            return str(exc)
        second_finished.set()
        return "admitted duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first)
        try:
            assert first_admitted.wait(10)
            second_future = pool.submit(second)
            assert second_started.wait(10)
            assert not second_finished.wait(0.25), "Second admission bypassed the Source lock"
        finally:
            release_first.set()
        first_future.result(timeout=10)
        assert (
            second_future.result(timeout=10)
            == "A retained import for this source is already active"
        )
    with factory.begin() as session:
        jobs = session.scalars(
            select(Job).where(Job.source_id == source_id, Job.kind == "retained_import")
        ).all()
        assert len(jobs) == 1
        assert jobs[0].status == "running"


def test_retained_documents_preserve_california_evidence_and_abilene_admission(
    retained_db, tmp_path
):
    factory, definitions, _synthetic_text = retained_db
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for source_id, policy in SOURCES.items():
        (source_root / policy["path"]).write_bytes(f"%PDF-synthetic-{source_id}".encode())

    first_pass = []
    source_ids = [
        "f17-stack-city-claim",
        "f17-stack-cec-filing",
        "f17-crusoe-impact",
    ]
    for source_id in source_ids[:2]:
        first_pass.append(_process_retained_f17(factory, source_id, source_root))
    first_pass.append(import_retained_document.run(source_ids[2], source_root))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        ca_project = session.scalar(
            select(Project).where(Project.location == "1200 Memorex Drive, Santa Clara, CA")
        )
        assert ca_project is not None and ca_project.region_status == "EXCLUDED"
        assert (
            session.scalar(
                select(PowerNeed.id).where(
                    PowerNeed.project_id == ca_project.id, PowerNeed.active.is_(True)
                )
            )
            is None
        )
        for source_id in ("f17-stack-city-claim", "f17-stack-cec-filing"):
            observation = session.scalar(
                select(Observation).where(Observation.source_id == source_id)
            )
            evidence = session.scalar(
                select(Evidence).where(Evidence.observation_id == observation.id)
            )
            interpretation = session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation.id)
            )
            assert evidence.provenance["retained_document"]["source_site"].endswith(", CA")
            assert evidence.extraction_location.startswith("PDF pp.")
            assert interpretation.status == "accepted"
            assert interpretation.assessment["admission_status"] == "regional_excluded"
        abilene = session.scalar(select(Project).where(Project.location == "near Abilene, Texas"))
        assert abilene is not None and abilene.region_status == "ELIGIBLE"
        assert (
            session.scalar(
                select(PowerNeed.id).where(
                    PowerNeed.project_id == abilene.id, PowerNeed.active.is_(True)
                )
            )
            is not None
        )
    assert first_pass[2]["signals"] == 1
    for source_id in source_ids[:2]:
        _process_retained_f17(factory, source_id, source_root)
    import_retained_document.run(source_ids[2], source_root)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 3
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 1


def _synthetic_tx_record(source_id: str) -> dict:
    policy = SOURCES[source_id]
    body = f"%PDF-synthetic-{source_id}".encode()
    return {
        "document_number": source_id,
        "title": "TX Shared Compute campus — retained filing/report",
        "abstract": (
            f"{policy['publisher']}\n\n"
            "The TX Shared Compute campus site address is 500 Synthetic Drive, Austin, TX. "
            "The project is planning a new utility service."
        ),
        "html_url": policy["url"],
        "publication_date": policy["publication_date"],
        "event_date": policy["event_date"],
        "event_date_label": policy["event_date_label"],
        "extraction_location": "PDF pp. 1",
        "source_hash": hashlib.sha256(body).hexdigest(),
        "retained_document": {
            "path": policy["path"],
            "sha256": hashlib.sha256(body).hexdigest(),
            "source_site": policy["location"],
            "project_name": "TX Shared Compute campus",
            "reviewed_spans": ["PDF pp. 1"],
        },
    }


def _process_synthetic_tx_source(factory, source_id: str, record: dict) -> dict:
    definition = {
        "id": source_id,
        "publisher": SOURCES[source_id]["publisher"],
        "endpoint": SOURCES[source_id]["url"],
        "family": "retained-public-document",
        "geography": "Texas",
        "industries": ["data centers"],
        "retrieval_method": "retained-document",
        "cadence_hours": 24,
    }
    with factory.begin() as session:
        job = Job(
            source_id=source_id,
            status="running",
            lease_owner="synthetic-retained-worker",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    with factory() as session:
        return process_records(
            session,
            job_id,
            "synthetic-retained-worker",
            1,
            definition,
            [record],
        )


def _process_retained_f17(factory, source_id: str, source_root: Path) -> dict:
    definitions = {item["id"]: item for item in load_registry()}
    record = retained_document.extract(source_id, source_root)
    with factory.begin() as session:
        job = Job(
            source_id=source_id,
            status="running",
            lease_owner="retained-regional-test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    with factory() as session:
        return process_records(
            session, job_id, "retained-regional-test", 1, definitions[source_id], [record]
        )


def test_two_synthetic_texas_retained_sources_merge_and_preserve_order_repair_reopen(
    retained_db,
):
    factory, _definitions, _synthetic_text = retained_db
    source_ids = ("test-retained-tx-a", "test-retained-tx-b")
    first, second = (_synthetic_tx_record(source_id) for source_id in source_ids)
    assert _process_synthetic_tx_source(factory, source_ids[0], first)["signals"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        project = session.scalar(select(Project))
        need = session.scalar(select(PowerNeed))
        assert project.region_status == "ELIGIBLE" and project.region_state == "TX"
        assert need is not None and need.active
        first_basis = need.admission_basis
        assert first_basis["source_id"] == source_ids[0]
        assert _need_admission_basis_is_current(session, need, project)
    _process_synthetic_tx_source(factory, source_ids[1], second)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 2
        need = session.scalar(select(PowerNeed))
        assert need.admission_basis == first_basis
        before_replay = _retained_state_snapshot(session)
    assert _process_synthetic_tx_source(factory, source_ids[0], first)["unchanged"] == 1
    assert _process_synthetic_tx_source(factory, source_ids[1], second)["unchanged"] == 1
    with factory() as session:
        assert _retained_state_snapshot(session) == before_replay


@pytest.mark.parametrize(
    ("first_source", "second_source"),
    [
        ("test-retained-tx-a", "test-retained-tx-b"),
        ("test-retained-tx-b", "test-retained-tx-a"),
    ],
)
def test_stack_need_basis_and_digest_stay_stable_in_either_source_order(
    retained_db, first_source, second_source
):
    factory, _definitions, _synthetic_text = retained_db
    first_record = _synthetic_tx_record(first_source)
    second_record = _synthetic_tx_record(second_source)
    _process_synthetic_tx_source(factory, first_source, first_record)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None
        first_basis = need.admission_basis
        assert first_basis["source_id"] == first_source
        project = session.get(Project, need.project_id)
        assert project is not None and _need_admission_basis_is_current(session, need, project)

    _process_synthetic_tx_source(factory, second_source, second_record)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None and need.admission_basis == first_basis
        before_replay = _retained_state_snapshot(session)

    _process_synthetic_tx_source(factory, first_source, first_record)
    with factory() as session:
        assert _retained_state_snapshot(session) == before_replay
    _process_synthetic_tx_source(factory, second_source, second_record)
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
    first_source = "test-retained-tx-a"
    repair_source = "test-retained-tx-b"
    first_record = _synthetic_tx_record(first_source)
    repair_record = _synthetic_tx_record(repair_source)
    _process_synthetic_tx_source(factory, first_source, first_record)
    with factory.begin() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None
        need.admission_basis = invalid_basis

    _process_synthetic_tx_source(factory, repair_source, repair_record)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None
        assert need.admission_basis["source_id"] == repair_source
        assert need.admission_basis["evidence_hash"] == repair_record["source_hash"]


def test_reopened_need_uses_new_retained_source_basis(retained_db, tmp_path):
    factory, _definitions, _synthetic_text = retained_db
    first_source = "test-retained-tx-a"
    reopen_source = "test-retained-tx-b"
    first_record = _synthetic_tx_record(first_source)
    reopen_record = _synthetic_tx_record(reopen_source)
    _process_synthetic_tx_source(factory, first_source, first_record)
    with factory.begin() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None
        need.active = False

    _process_synthetic_tx_source(factory, reopen_source, reopen_record)
    with factory() as session:
        need = session.scalar(select(PowerNeed).where(PowerNeed.activity_key == "utility-service"))
        assert need is not None and need.active
        assert need.admission_basis["source_id"] == reopen_source


def test_failed_import_rolls_back_source_records_and_leaves_failed_receipt(
    retained_db, tmp_path, monkeypatch
):
    factory, _definitions, _synthetic_text = retained_db
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_ids = ("f17-stack-city-claim", "f17-stack-cec-filing")
    for source_id in source_ids:
        policy = SOURCES[source_id]
        (source_root / policy["path"]).write_bytes(f"%PDF-synthetic-{source_id}".encode())
    _process_retained_f17(factory, "f17-stack-cec-filing", source_root)
    with factory() as session:
        before = _retained_state_snapshot(session)
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        ca_project = session.scalar(select(Project))
        assert ca_project is not None and ca_project.region_status == "EXCLUDED"
        assert (
            session.scalar(
                select(PowerNeed.id).where(
                    PowerNeed.project_id == ca_project.id, PowerNeed.active.is_(True)
                )
            )
            is None
        )

    with pytest.raises(RuntimeError, match="accepted linked need"):
        import_retained_document.run(source_id, source_root)

    with factory() as session:
        assert _retained_state_snapshot(session) == before
        failed = session.scalar(
            select(Job).where(Job.source_id == source_id, Job.kind == "retained_import")
        )
        assert failed is not None and failed.status == "failed"
        assert failed.error == "Retained import failed: RuntimeError"


def test_reviewed_synthetic_hash_update_retains_old_version_and_relinks_current_need(
    retained_db, monkeypatch
):
    factory, _definitions, _synthetic_text = retained_db
    source_id = "test-retained-tx-a"
    record = _synthetic_tx_record(source_id)
    original_hash = record["source_hash"]
    _process_synthetic_tx_source(factory, source_id, record)
    revised_body = f"%PDF-synthetic-{source_id}|reviewed-v2".encode()
    revised_hash = hashlib.sha256(revised_body).hexdigest()
    monkeypatch.setitem(SOURCES, source_id, {**SOURCES[source_id], "sha256": revised_hash})
    revised = {**record, "source_hash": revised_hash}
    revised["retained_document"] = {**record["retained_document"], "sha256": revised_hash}
    _process_synthetic_tx_source(factory, source_id, revised)

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
