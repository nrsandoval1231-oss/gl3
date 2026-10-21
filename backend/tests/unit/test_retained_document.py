from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gridlens.domain.signal_admission import (
    F17_RETAINED_ACCEPTED_REASON,
    admit_standalone,
    admitted_from_source,
)
from gridlens.ingestion.adapters import retained_document
from gridlens.ingestion.adapters.retained_document import SOURCES, extract

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.import_retained_document import assert_isolated_database


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
