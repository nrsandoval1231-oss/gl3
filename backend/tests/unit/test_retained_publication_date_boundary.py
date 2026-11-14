"""Publication dates must come from explicit metadata or source date headers."""

import hashlib
import json
from datetime import date
from pathlib import Path

from gridlens.ingestion.adapters.retained_company_projects import (
    _as_date,
    interpret_retained_company_project,
    retained_record_hash,
    retained_records,
)


def _write_corpus(tmp_path: Path, *, publication_metadata: str | None):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    excerpt = (
        "The new data center campus in Dallas, Texas is under construction. "
        "Work started May 1, 2024."
    )
    source = {
        "url": "https://example.com/retained-project",
        "title": "Example announces Dallas campus",
        "excerpts": [excerpt],
        "publication_date_metadata": publication_metadata,
        "observation_date": "2024-06-01",
    }
    artifact = json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    (source_dir / "example.json").write_bytes(artifact)
    manifest = [
        {
            "file": "sources/example.json",
            "sha256": hashlib.sha256(artifact).hexdigest(),
            "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
        }
    ]
    (tmp_path / "source-hashes.json").write_text(json.dumps(manifest))
    return excerpt


def test_body_event_date_is_not_a_publication_date():
    body = (
        "The new data center campus in Dallas, Texas is under construction. "
        "Work started May 1, 2024."
    )
    assert _as_date(None, body) is None


def test_date_inside_a_nonpublication_header_is_not_trusted():
    for header in (
        "Construction starts May 1, 2024",
        "Expected energization: May 1, 2024",
        "Opening Date: May 1, 2024",
        "Last updated: May 1, 2024",
    ):
        assert _as_date(None, header) is None


def test_titlecase_prose_cannot_impersonate_a_city_state_dateline():
    for text in (
        "Work Started, Dallas – May 1, 2024 – Construction begins next month.",
        "Work starts in Dallas, TX – May 1, 2024 – Construction will continue.",
        "The project opens in Dallas, Texas – May 1, 2024 – Full operations follow.",
        "Construction starts in Dallas, TX – May 1, 2024",
        "Work Starts In Dallas, TX – May 1, 2024 – ...",
        "The Project Opens In Dallas, Texas – May 1, 2024 – ...",
        "CONSTRUCTION STARTS IN DALLAS, TX – May 1, 2024",
        "Construction Started, TX – May 1, 2024 – ...",
        "Opening Date, Texas – May 1, 2024 – ...",
    ):
        assert _as_date(None, text) is None


def test_metadata_with_only_year_or_quarter_does_not_become_exact_day():
    body = "The new facility will begin operation on May 1, 2024."
    assert _as_date("2024", body) is None
    assert _as_date("2024-Q2", body) is None
    assert _as_date("2024-05", body) is None


def test_exact_metadata_and_standalone_publication_date_headers_are_supported():
    assert _as_date("2024-09-10T08:30:00+00:00", "") == date(2024, 9, 10)
    assert _as_date(None, "Published:January 25, 2024\nArticle text") == date(2024, 1, 25)
    assert _as_date(None, "September 24, 2026\nArticle text") == date(2026, 9, 24)
    assert _as_date(None, "Indianapolis, IN – May 1, 2024 – Publisher release.") == date(2024, 5, 1)


def test_native_databank_and_cyrusone_datelines_remain_exact():
    corpus = Path(__file__).resolve().parents[3] / "eval/customer-commercial-v1"
    records, _held = retained_records(corpus)
    by_url = {record["html_url"]: record for record in records}
    assert (
        by_url[
            "https://www.databank.com/resources/press-releases/"
            "databank-announces-development-of-480mw-data-center-campus-in-south-dallas/"
        ]["publication_date"]
        == "2024-09-10"
    )
    assert (
        by_url[
            "https://www.cyrusone.com/resources/press-releases/"
            "cyrusone-and-calpine-announce-newhyperscale-data-center-development-in-texas"
        ]["publication_date"]
        == "2025-07-30"
    )


def test_untrusted_body_event_date_holds_the_real_adapter_record(tmp_path):
    _write_corpus(tmp_path, publication_metadata=None)
    records, held = retained_records(tmp_path)
    assert records == []
    assert len(held) == 1
    assert "No exact source publication date" in held[0]["reason"]


def test_interpreter_rejects_publication_day_without_header_or_metadata(tmp_path):
    _write_corpus(tmp_path, publication_metadata="2024-05-01")
    records, _held = retained_records(tmp_path)
    assert len(records) == 1
    record = records[0]
    context = record["retained_company_project"]
    record["publication_date_metadata"] = None
    context["publication_date_metadata"] = None
    record["source_hash"] = retained_record_hash(record)
    context["content_hash"] = record["source_hash"]
    assert interpret_retained_company_project(record) is None
