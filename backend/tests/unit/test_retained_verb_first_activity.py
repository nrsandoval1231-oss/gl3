"""Controls for verb-first construction relations in retained source text."""

import hashlib
import json
from pathlib import Path

import pytest

from gridlens.domain.project_activity_binding import activity_is_bound_to_project
from gridlens.ingestion.adapters.retained_company_projects import (
    interpret_retained_company_project,
    retained_records,
)


def _span(text: str, value: str) -> tuple[int, int]:
    start = text.index(value)
    return start, start + len(value)


def _crusoe_sentence() -> str:
    return (
        "Construction has begun at the Lancium Clean Campus in Abilene, Texas "
        "on an additional six data centers."
    )


def test_verb_first_construction_binds_exact_site_and_location_spans():
    text = _crusoe_sentence()

    assert activity_is_bound_to_project(
        text,
        subject_span=_span(text, "Lancium Clean Campus"),
        activity_span=_span(text, "Construction has begun"),
        site_span=_span(text, "in Abilene, Texas"),
    )


@pytest.mark.parametrize(
    ("text", "activity_phrase"),
    [
        (
            "Construction has begun at the Lancium Clean Campus adjacent to South Campus "
            "in Abilene, Texas on six data centers.",
            "Construction has begun",
        ),
        (
            "Construction has begun at the Lancium Clean Campus in Abilene, Texas, "
            "but the construction status is hypothetical.",
            "Construction has begun",
        ),
        (
            "Construction has not begun at the Lancium Clean Campus in Abilene, Texas.",
            "Construction has not begun",
        ),
    ],
    ids=["competing-site", "hypothetical-status", "negated-status"],
)
def test_verb_first_relation_rejects_competing_or_adverse_activity(text: str, activity_phrase: str):
    assert not activity_is_bound_to_project(
        text,
        subject_span=_span(text, "Lancium Clean Campus"),
        activity_span=_span(text, activity_phrase),
        site_span=_span(text, "in Abilene, Texas"),
    )


@pytest.mark.parametrize(
    "text",
    [
        "A separate South Campus is planned. Construction has begun at the Lancium Clean "
        "Campus in Abilene, Texas.",
        "Construction has begun after a separate South Campus update at the Lancium Clean "
        "Campus in Abilene, Texas.",
    ],
    ids=["unrelated-prefix", "unrelated-intervening-clause"],
)
def test_verb_first_relation_does_not_cross_unrelated_text(text: str):
    assert not activity_is_bound_to_project(
        text,
        subject_span=_span(text, "Lancium Clean Campus"),
        activity_span=_span(text, "Construction has begun"),
        site_span=_span(text, "in Abilene, Texas"),
    )


def test_retained_crusoe_excerpt_admits_named_lancium_site_with_literal_texas(tmp_path):
    source_path = (
        Path(__file__).resolve().parents[3]
        / "eval"
        / "customer-commercial-v1"
        / "sources"
        / "crusoe.json"
    )
    corpus = tmp_path / "retained-crusoe-verb-first"
    sources_dir = corpus / "sources"
    sources_dir.mkdir(parents=True)
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    (sources_dir / "crusoe.json").write_bytes(source_bytes)
    body = "\n\n".join(source["excerpts"])
    manifest = [
        {
            "file": "sources/crusoe.json",
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "url": source["url"],
            "excerpt_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
    ]
    (corpus / "source-hashes.json").write_text(json.dumps(manifest), encoding="utf-8")
    records, held = retained_records(corpus)
    record = next(
        row
        for row in records
        if "sources/crusoe.json" in row["retained_company_project"]["source_files"]
    )
    context = record["retained_company_project"]

    assert context["project_name"] == "Lancium Clean Campus"
    assert context["project_location"] == "Abilene, TX"
    assert context["activity_key"] == "construction"
    assert context["activity_quote"] == "Construction has begun"
    assert context["location_quote"] == "in Abilene, Texas"
    assert interpret_retained_company_project(record) is not None
    body = record["abstract"]
    for field in ("project", "location", "activity"):
        start, end = context["source_spans"][field]
        assert body[start:end] == context[f"{field}_quote"]
    assert not any("sources/crusoe.json" in item.get("source_files", []) for item in held)
