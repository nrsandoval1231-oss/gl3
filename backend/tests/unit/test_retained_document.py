from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from gridlens.domain.signal_admission import (
    F17_RETAINED_ACCEPTED_REASON,
    admit_standalone,
    admitted_from_source,
)
from gridlens.ingestion.adapters import retained_document
from gridlens.ingestion.adapters.retained_document import (
    SOURCES,
    STACK_CONFLICT_ACTION,
    STACK_CONFLICT_REASON,
    extract,
    stack_service_conflict,
)

IMPORT_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_retained_document.py"
IMPORT_SPEC = importlib.util.spec_from_file_location("retained_document_unit_cli", IMPORT_SCRIPT)
assert IMPORT_SPEC is not None and IMPORT_SPEC.loader is not None
import_retained_document = importlib.util.module_from_spec(IMPORT_SPEC)
IMPORT_SPEC.loader.exec_module(import_retained_document)
assert_isolated_database = import_retained_document.assert_isolated_database


@pytest.mark.parametrize("source_id", sorted(SOURCES))
def test_exact_retained_pdf_extracts_bounded_reviewed_pages(source_id, tmp_path, monkeypatch):
    text_by_source = {
        "f17-stack-city-claim": (
            "SVY02A Memorex Junction data center at 1200 Memorex Drive, Santa Clara, California. "
            "18 MVA through 2028; earlier schedule 28 MVA and 31 MVA."
        ),
        "f17-stack-cec-filing": (
            "Memorex Junction data center at 1200 Memorex Drive, Santa Clara, California. "
            "Vastly underserved; draft agreement. Table E1 - Available Capacity Schedule "
            "Capacity Paid Development (MVA) Fee Payment Capacity 28 10 20 31 10 30."
        ),
        "f17-crusoe-impact": (
            "Abilene Stargate campus near Abilene, Texas. Natural gas turbines provide "
            "temporary bridge power while grid upgrades catch up."
        ),
    }
    body = b"%PDF-synthetic-review-fixture"
    policy = {
        **SOURCES[source_id],
        "path": "synthetic.pdf",
        "sha256": hashlib.sha256(body).hexdigest(),
        "spans": ((1, 1),),
    }
    monkeypatch.setitem(SOURCES, source_id, policy)
    monkeypatch.setattr(
        retained_document,
        "PdfReader",
        lambda _stream: type(
            "Reader",
            (),
            {
                "pages": [
                    type(
                        "Page",
                        (),
                        {"extract_text": lambda _self: text_by_source[source_id]},
                    )()
                ]
            },
        )(),
    )
    (tmp_path / "synthetic.pdf").write_bytes(body)
    record = extract(source_id, tmp_path)
    assert record["source_hash"] == policy["sha256"]
    assert record["extraction_location"]
    assert record["retained_document"]["reviewed_spans"]
    assert record["retained_document"]["project_name"] in record["title"]
    assert record["retained_document"]["source_site"] == policy["location"]
    assert len(record["abstract"]) <= 80_100


def test_changed_retained_pdf_is_rejected(tmp_path):
    source_id = "f17-crusoe-impact"
    root = tmp_path / "source"
    root.mkdir()
    path = root / SOURCES[source_id]["path"]
    path.write_bytes(b"%PDF-" + b"x" * 20)
    with pytest.raises(ValueError, match="hash mismatch"):
        extract(source_id, root)


def test_retained_pdf_size_is_checked_before_read(tmp_path, monkeypatch):
    source_id = "f17-stack-city-claim"
    root = tmp_path / "source"
    root.mkdir()
    path = root / SOURCES[source_id]["path"]
    with path.open("wb") as handle:
        handle.truncate(retained_document.MAX_BODY_BYTES + 1)
    with pytest.raises(ValueError, match="size limit"):
        extract(source_id, root)


def test_unreviewed_source_id_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="Unreviewed"):
        extract("f17-unreviewed", tmp_path)


def test_stack_conflict_proof_only_carries_attributed_context_for_current_exact_sources():
    item = {
        "name": "SVY02A / Memorex Junction data center",
        "location": "1200 Memorex Drive, Santa Clara, CA",
        "evidence": [
            {
                "id": source_id,
                "source_id": source_id,
                "url": SOURCES[source_id]["url"],
                "content_hash": SOURCES[source_id]["sha256"],
                "abstract": passage,
                "assessment_current": True,
            }
            for source_id, passage in (
                (
                    "f17-stack-city-claim",
                    "At 1200 Memorex Drive in Santa Clara, STACK reports an 18 MVA "
                    "cap until 2028 rather than 28 MVA and 31 MVA.",
                ),
                (
                    "f17-stack-cec-filing",
                    "At 1200 Memorex Drive in Santa Clara, the draft Table E1 "
                    "capacity schedule (MVA) lists 28 and 31.",
                ),
            )
        ],
    }
    proof = stack_service_conflict(item)
    assert proof.status == "verified"
    assert proof.reason == STACK_CONFLICT_REASON
    assert proof.next_action == STACK_CONFLICT_ACTION

    item["evidence"][1]["content_hash"] = "0" * 64
    stale = stack_service_conflict(item)
    assert stale.status == "handled_without_proof"
    assert stale.reason is None and stale.next_action is None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://local:unused@localhost/gridlens_test",
        "postgresql+psycopg://local:unused@localhost/gl3_pr105_f17_acceptance_20261021",
    ],
)
def test_import_database_guard_allows_only_explicit_disposable_databases(url):
    assert assert_isolated_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://local:unused@localhost/gridlens",
        "postgresql+psycopg://local:unused@localhost/app_v2",
        "postgresql+psycopg://local:unused@localhost/app_v2_test_extra",
    ],
)
def test_import_database_guard_rejects_application_databases(url):
    with pytest.raises(ValueError, match="isolated database"):
        assert_isolated_database(url)


@pytest.mark.parametrize(
    ("source_id", "family", "activity"),
    [
        ("f17-stack-city-claim", "retained-public-document", "utility-service"),
        ("f17-crusoe-impact", "retained-operator-publication", "bridge-power"),
    ],
)
def test_admission_is_exact_source_and_activity(source_id, family, activity):
    policy = SOURCES[source_id]
    title = f"{policy['project_cue']} data center"
    abstract = " ".join([policy["site_cue"], *policy["location_cues"]])
    result = admit_standalone(
        source_id=source_id,
        family=family,
        retrieval_method="retained-document",
        accepted=True,
        activity=activity,
        title=title,
        abstract=abstract,
        dated=True,
        citation_url=policy["url"],
        identified_project=True,
    )
    assert result.admitted
    rejected = admit_standalone(
        source_id=source_id,
        family=family,
        retrieval_method="retained-document",
        accepted=True,
        activity="temporary-power",
        title=title,
        abstract=abstract,
        dated=True,
        citation_url=policy["url"],
        identified_project=True,
    )
    assert not rejected.admitted


@pytest.mark.parametrize("source_id", sorted(SOURCES))
def test_retained_admission_basis_reason_matches_source_revalidation(source_id):
    policy = SOURCES[source_id]
    family = (
        "retained-operator-publication"
        if source_id == "f17-crusoe-impact"
        else "retained-public-document"
    )
    body_hash = "synthetic-reviewed-hash"
    project_name = f"{policy['project_cue']} data center"
    if policy.get("project_suffix"):
        project_name = f"{policy['project_cue']} {policy['project_suffix']}"
    title = f"{policy['project_cue']} retained source"
    abstract = " ".join([policy["site_cue"], *policy["location_cues"]])
    standalone = admit_standalone(
        source_id=source_id,
        family=family,
        retrieval_method="retained-document",
        accepted=True,
        activity=policy["activity"],
        title=title,
        abstract=abstract,
        dated=True,
        citation_url=policy["url"],
        identified_project=True,
    )
    source = SimpleNamespace(id=source_id, family=family, retrieval_method="retained-document")
    evidence = SimpleNamespace(
        content_hash=body_hash,
        provenance={
            "retained_document": {
                "sha256": policy["sha256"],
                "path": policy["path"],
                "source_site": policy["location"],
                "project_name": project_name,
                "reviewed_spans": ["PDF pp. 1-1"],
            }
        },
        url=policy["url"],
        published_at=policy.get("publication_date"),
        event_date=policy.get("event_date") or "2025-01-01",
    )
    assessment = {
        "decision": "accepted",
        "evidence_hash": body_hash,
        "subject": project_name,
        "location": policy["location"],
        "power_activity": policy["activity"],
    }

    persisted = admitted_from_source(source, assessment, evidence)

    assert standalone.admitted and persisted.admitted
    assert standalone.reason == persisted.reason == F17_RETAINED_ACCEPTED_REASON


def test_cec_admission_normalizes_only_pdf_whitespace_wrapping():
    policy = SOURCES["f17-stack-cec-filing"]
    result = admit_standalone(
        source_id="f17-stack-cec-filing",
        family="retained-public-document",
        retrieval_method="retained-document",
        accepted=True,
        activity="utility-service",
        title="SVY02A / Memorex Junction data center",
        abstract=(
            "1200 Memorex\nDrive, Santa\nClara; 28 MVA and 31 MVA remain reported only as MVA."
        ),
        dated=True,
        citation_url=policy["url"],
        identified_project=True,
    )
    assert result.admitted
