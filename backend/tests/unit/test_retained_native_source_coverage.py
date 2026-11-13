"""Source-bound coverage for retained public project announcements."""

import hashlib
import json
from pathlib import Path

from gridlens.ingestion.adapters.retained_company_projects import (
    _candidate,
    interpret_retained_company_project,
    retained_records,
)


def _corpus_root() -> Path:
    return Path(__file__).resolve().parents[3] / "eval" / "customer-commercial-v1"


def test_aligned_park_clause_keeps_exact_location_without_inventing_state():
    records, held = retained_records(_corpus_root())
    record = next(
        row
        for row in records
        if "sources/aligned.json" in row["retained_company_project"]["source_files"]
    )
    context = record["retained_company_project"]

    assert context["project_location"] == "Conesville Industrial Park"
    assert "," not in context["project_location"]
    assert context["location_quote"] == "inside the Conesville Industrial Park"
    assert context["activity_key"] == "facility-expansion"
    assert context["project_aliases"] == []
    assert interpret_retained_company_project(record) is not None
    assert not any("sources/aligned.json" in row.get("source_files", []) for row in held)
    _assert_retained_spans(record)


def test_switch_named_campus_uses_direct_round_rock_action_and_literal_alias():
    records, held = retained_records(_corpus_root())
    record = next(
        row
        for row in records
        if "sources/switch.json" in row["retained_company_project"]["source_files"]
    )
    context = record["retained_company_project"]

    assert context["project_name"] == "Fifth Prime data center campus"
    assert context["project_location"] == "Round Rock, TX"
    assert context["location_quote"] == "in Round Rock, Texas"
    assert context["activity_key"] == "facility-expansion"
    assert context["activity_quote"] == "to construct"
    assert context["project_aliases"] == ["The Rock"]
    assert "Austin" not in context["project_location"]
    assert "Houston" not in context["project_location"]
    assert "185" not in context["activity_quote"]
    assert interpret_retained_company_project(record) is not None
    assert not any("sources/switch.json" in row.get("source_files", []) for row in held)
    _assert_retained_spans(record)


def test_switch_portfolio_and_neighbor_capacity_text_does_not_scope_to_rock():
    from gridlens.domain.customer_intelligence import extract_customer_facts
    from gridlens.intelligence.customer_intelligence import scope_customer_facts

    records, _held = retained_records(_corpus_root())
    record = next(
        row
        for row in records
        if "sources/switch.json" in row["retained_company_project"]["source_files"]
    )
    context = record["retained_company_project"]
    payload = extract_customer_facts(
        record["abstract"],
        project_id="switch-source-scope-control",
        source={"url": record["html_url"], "content_hash": record["source_hash"]},
    )
    scoped = scope_customer_facts(
        payload,
        context["project_name"],
        context["project_location"],
        source_text=record["abstract"],
        project_aliases=context["project_aliases"],
    )

    assert payload["capacity_claims"] == []
    assert scoped["capacity_claims"] == []
    assert scoped["timeline_claims"] == []


def test_direct_construction_clause_cannot_bind_a_different_actor_to_named_campus():
    text = (
        "Acme (“Acme”), a technology company, today announced the primary location of its "
        "Alpha data center campus in Texas. The land purchase agreement with Acme will allow "
        "Beta to construct new data center space next to Beta headquarters in Round Rock, "
        "Texas. The Alpha campus will be called “Alpha One”."
    )

    assert _candidate([text]).state == "HOLD"


def test_direct_construction_clause_holds_when_paragraph_names_two_physical_campuses():
    text = (
        "Acme (“Acme”), a technology company, today announced the primary location of its "
        "Alpha data center campus in Texas. Acme also announced its Beta data center campus. "
        "The land purchase agreement with Acme will allow Acme to construct new data center "
        "space next to Acme headquarters in Round Rock, Texas. "
        "The Alpha campus will be called “Alpha One”."
    )

    assert _candidate([text]).state == "HOLD"


def test_named_project_action_requires_active_announcement_and_direct_project_agreement():
    project_announcement = (
        "Acme (“Acme”), a technology company, today announced the primary location of its "
        "Alpha data center campus in Texas. "
    )
    action = (
        "The land purchase agreement with Acme will allow Acme to construct new data center "
        "space next to Acme headquarters in Round Rock, Texas. "
        "The Alpha campus will be called “Alpha One”."
    )
    assert _candidate([project_announcement + action]).state == "CANDIDATE"

    separate_campus = "For a separate campus, " + action
    assert _candidate([project_announcement + separate_campus]).state == "HOLD"
    for intervening in (
        "A separate campus is planned in Round Rock. ",
        "The following agreement concerns a different site. ",
    ):
        assert _candidate([project_announcement + intervening + action]).state == "HOLD"
    negated_announcement = project_announcement.replace("today announced", "has not announced")
    assert _candidate([negated_announcement + action]).state == "HOLD"
    negated_name = project_announcement + action.replace(
        "The Alpha campus will be called", "It is not true that the Alpha campus will be called"
    )
    assert _candidate([negated_name]).state == "HOLD"


def test_named_project_action_does_not_cross_markdown_paragraph_boundaries():
    first = (
        "Acme (“Acme”), a technology company, today announced the primary location of its "
        "Alpha data center campus in Texas."
    )
    second = (
        "The land purchase agreement with Acme will allow Acme to construct new data center "
        "space next to Acme headquarters in Round Rock, Texas. "
        "The Alpha campus will be called “Alpha One”."
    )
    for separator in ("\n\n", " \n\n", "  \n\n", "\r\n\r\n"):
        assert _candidate([first + separator + second]).state == "HOLD"


def test_named_campus_cancellation_uses_the_exact_called_alias_and_canonical_name():
    project = (
        "Acme (“Acme”), a technology company, today announced the primary location of its "
        "Alpha data center campus in Texas. "
        "The land purchase agreement with Acme will allow Acme to construct new data center "
        "space next to Acme headquarters in Round Rock, Texas. "
        "The Alpha campus will be called “Alpha One”. "
    )
    for status in (
        "Alpha One has been canceled.",
        "The Alpha campus has been canceled.",
    ):
        assert _candidate([project + status]).state == "HOLD"
    assert _candidate([project + "The Beta campus will be called “Alpha One”."]).state == "HOLD"
    assert (
        _candidate([project + "The Alpha East campus will be called “Alpha One”."]).state == "HOLD"
    )

    source = json.loads((_corpus_root() / "sources" / "switch.json").read_text())
    for status in (
        "The Rock has been canceled.",
        "The Rock campus has been canceled.",
        "The Fifth Prime campus has been canceled.",
    ):
        sections = list(source["excerpts"])
        sections[0] += " " + status
        assert _candidate(sections).state == "HOLD"


def test_alias_reassigned_to_foreign_campus_withholds_switch_site_binding():
    source = json.loads((_corpus_root() / "sources" / "switch.json").read_text())
    sections = [
        *source["excerpts"],
        "The Beta campus will be called “The Rock”. The Rock has 500 MW of IT load.",
    ]

    assert _candidate(sections).state == "HOLD"


def test_alias_cancellation_is_preserved_in_adverse_status_receipt(tmp_path):
    source = json.loads((_corpus_root() / "sources" / "switch.json").read_text())
    source["excerpts"][0] += " The Rock campus has been canceled."
    target = tmp_path / "sources" / "switch.json"
    target.parent.mkdir(parents=True)
    encoded = json.dumps(source, ensure_ascii=False, indent=2).encode()
    target.write_bytes(encoded)
    body = "\n\n".join(source["excerpts"])
    manifest = [
        {
            "file": "sources/switch.json",
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "url": source["url"],
            "excerpt_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
    ]
    (tmp_path / "source-hashes.json").write_text(json.dumps(manifest))

    records, held = retained_records(tmp_path)

    assert len(records) == 1
    context = records[0]["retained_company_project"]
    assert context["status"] == "adverse_status_review"
    assert context["status_quote"] == "The Rock campus has been canceled."
    assert held[0]["reason"] == context["status_reason"]


def test_retained_source_inputs_are_available_for_hash_checked_replay():
    root = _corpus_root()
    for filename in ("aligned.json", "switch.json", "applied.json"):
        source = json.loads((root / "sources" / filename).read_text())
        assert source["excerpts"]
    assert (root / "source-hashes.json").is_file()


def _assert_retained_spans(record: dict) -> None:
    context = record["retained_company_project"]
    body = record["abstract"]
    for field in ("project", "location", "activity"):
        span = context["source_spans"][field]
        assert body[span[0] : span[1]] == context[f"{field}_quote"]
    for alias, span in context["alias_spans"].items():
        assert body[span[0] : span[1]] == context["alias_quotes"][alias]
