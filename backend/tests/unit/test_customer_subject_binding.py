"""Source-local identity binding before customer claims can be published."""

import json

import pytest

from gridlens.domain.customer_intelligence import extract_customer_facts
from gridlens.domain.customer_subjects import resolve_claim_subject
from gridlens.intelligence.customer_intelligence import (
    _verified_project_owner_names,
    extract_commissioning_plan,
    persist_customer_facts,
    scope_customer_facts,
)

SOURCE = {
    "url": "https://owner.example/project-update",
    "evidence_id": "subject-evidence",
    "content_hash": "b" * 64,
    "published_at": "2025-07-30",
    "observed_at": "2026-11-12T00:00:00Z",
    "authority": "unknown",
    "verification_status": "reported",
}


def scope(text, project_name, *, aliases=(), owners=()):
    payload = extract_customer_facts(text, project_id="project-1", source=SOURCE)
    return scope_customer_facts(
        payload,
        project_name,
        source_text=text,
        project_aliases=list(aliases),
        trusted_owner_names=list(owners),
    )


def test_verified_owner_possessive_binds_exact_native_site_alias():
    quote = "Applied Digital’s Ellendale campus is designed to host 400 MW of critical IT load."
    raw = extract_customer_facts(quote, project_id="project-1", source=SOURCE)

    assert scope_customer_facts(
        raw,
        "Ellendale campus",
        source_text=quote,
        trusted_owner_names=["Applied Digital"],
    )["capacity_claims"]
    assert not scope_customer_facts(raw, "Ellendale campus", source_text=quote)["capacity_claims"]


def test_cyrusone_adjacent_deal_anaphora_preserves_operational_deadline():
    text = (
        "Calpine announced a new 190-megawatt agreement with CyrusOne to serve a new data "
        "center adjacent to the Thad Hill Energy Center in Bosque County, Texas. "
        "The deal secures power, grid connection, and land to support a new facility that "
        "is under construction and expected to be operational by the fourth quarter of 2026."
    )
    result = scope(
        text,
        "CyrusOne Bosque facility",
        aliases=["new data center adjacent to the Thad Hill Energy Center"],
    )

    assert len(result["timeline_claims"]) == 1
    claim = result["timeline_claims"][0]
    assert (claim["event_type"], claim["label"], claim["precision"], claim["qualifier"]) == (
        "operational_target",
        "fourth quarter of 2026",
        "quarter",
        "deadline",
    )
    binding = claim["subject_binding"]
    assert binding["subject_kind"] == "adjacent_anaphora"
    assert binding["source_hash"] == SOURCE["content_hash"]
    assert binding["occurrences"][0]["antecedent_span"]


def test_named_campus_antecedent_binds_later_phase_and_total_claims():
    text = (
        "The South Dallas land will become home to the new “Red Oak Campus” accommodating "
        "up to eight, 2-story data centers of 425,000 gross square feet each, totaling as "
        "much as 3.4M square feet. The Phase 1 design of the site will feature 4 buildings "
        "and a 400MW sub-station from Oncor that can deliver up to 240MW of critical IT "
        "power with the ability to increase this in Phase 2 for a total of 480MW across "
        "all 8 buildings."
    )
    result = scope(text, "Red Oak Campus")

    facts = {
        (claim["value_mw"], claim["scope_id"], claim["qualifier"]): claim
        for claim in result["capacity_claims"]
    }
    phase = facts[("240", "project-1:phase:1", "up_to")]
    total = facts[("480", "project-1:site", "up_to")]
    assert total["includes_scope_ids"] == ["project-1:phase:1", "project-1:phase:2"]
    assert phase["subject_binding"]["subject_kind"] == "adjacent_anaphora"
    assert total["subject_binding"]["subject_kind"] == "adjacent_anaphora"

    foreign = text.replace("Red Oak Campus", "Dallas Campus")
    assert not scope(foreign, "Red Oak Campus")["capacity_claims"]


def test_foreign_subject_and_ambiguous_anaphora_do_not_inherit_target_identity():
    foreign = "Orion Data Center announced construction. Dallas Campus has 999 MW of IT load."
    assert not scope(foreign, "Orion Data Center")["capacity_claims"]

    ambiguous = (
        "Orion Data Center announced construction. Another Campus is also planned. "
        "The facility has 100 MW of IT load."
    )
    result = scope(ambiguous, "Orion Data Center")
    assert result["capacity_claims"] == []

    foreign_anaphor = (
        "Orion Data Center announced construction. "
        "The facility at Dallas Campus has 999 MW of IT load."
    )
    assert not scope(foreign_anaphor, "Orion Data Center")["capacity_claims"]

    misleading_relation = (
        "Beta Campus is being built for Alpha Campus. The facility has 100 MW of IT load."
    )
    assert not scope(
        misleading_relation,
        "Alpha Campus",
        aliases=["Alpha Campus"],
    )["capacity_claims"]


def test_selected_subject_cannot_lend_claims_to_a_second_site_in_same_clause():
    text = (
        "Orion Data Center has 100 MW of IT load and another Dallas Campus has 999 MW of IT load."
    )
    assert not scope(text, "Orion Data Center")["capacity_claims"]


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("North Campus is adjacent to South Campus with 500 MW of IT load.", "capacity_claims"),
        (
            "North Campus provides access to South Campus, which has 500 MW of IT load.",
            "capacity_claims",
        ),
        (
            "North Campus is adjacent to South Campus. The facility has 500 MW of IT load.",
            "capacity_claims",
        ),
        (
            "North Campus is adjacent to South Campus. "
            "The facility is expected to be energized in 2027.",
            "timeline_claims",
        ),
        ("North Campus uses South Campus’s 500 MW of IT load.", "capacity_claims"),
        (
            "North Campus is smaller than South Campus with 500 MW of IT load.",
            "capacity_claims",
        ),
        (
            "North Campus is adjacent to South Campus, whose IT load is 500 MW.",
            "capacity_claims",
        ),
        ("North Campus is alongside South Campus with 500 MW of IT load.", "capacity_claims"),
    ],
)
def test_neighbor_site_cannot_supply_claims_through_relation_or_anaphora(text, field):
    assert scope(text, "North Campus")[field] == []


def test_direct_capacity_predicate_remains_supported_after_structural_binding():
    result = scope("North Campus has 500 MW of critical IT load.", "North Campus")
    assert [claim["value_mw"] for claim in result["capacity_claims"]] == ["500"]


@pytest.mark.parametrize(
    "text",
    [
        "North Campus has 100 MW of IT load connected to South Campus with 500 MW of IT load.",
        "North Campus has 100 MW of IT load, compared to 500 MW of IT load elsewhere.",
    ],
)
def test_owned_first_amount_does_not_own_a_later_amount(text):
    result = scope(text, "North Campus")
    assert [claim["value_mw"] for claim in result["capacity_claims"]] == ["100"]


def test_owned_first_date_does_not_own_a_later_competing_site_date():
    text = "North Campus is expected to be energized in 2027, connected to South Campus "
    text += "expected to be energized in 2028."
    result = scope(text, "North Campus")
    assert [claim["label"] for claim in result["timeline_claims"]] == ["2027"]


@pytest.mark.parametrize(
    "text",
    [
        "North Campus has 100 acres connected to South Campus with 500 MW of IT load.",
        "North Campus has 100 staff supporting South Campus with 500 MW of IT load.",
        "North Campus has 100 MW transformers connected to South Campus with 500 MW of IT load.",
    ],
)
def test_untyped_owned_quantity_does_not_license_neighbor_electrical_claim(text):
    assert scope(text, "North Campus")["capacity_claims"] == []

    payload = extract_customer_facts(text, project_id="project-1", source=SOURCE)
    assert scope_customer_facts(payload, "North Campus")["capacity_claims"] == []


def test_legacy_quote_only_scope_cannot_bypass_structural_subject_checks():
    neighbor = "North Campus is adjacent to South Campus with 500 MW of IT load."
    neighbor_payload = extract_customer_facts(neighbor, project_id="project-1", source=SOURCE)
    assert not scope_customer_facts(neighbor_payload, "North Campus")["capacity_claims"]

    multiple = (
        "North Campus has 100 MW of IT load connected to South Campus with 500 MW of IT load."
    )
    multiple_payload = extract_customer_facts(multiple, project_id="project-1", source=SOURCE)
    scoped_multiple = scope_customer_facts(multiple_payload, "North Campus")
    assert [claim["value_mw"] for claim in scoped_multiple["capacity_claims"]] == ["100"]

    timeline = (
        "North Campus is expected to be energized in 2027, connected to South Campus "
        "expected to be energized in 2028."
    )
    timeline_payload = extract_customer_facts(timeline, project_id="project-1", source=SOURCE)
    scoped_timeline = scope_customer_facts(timeline_payload, "North Campus")
    assert [claim["label"] for claim in scoped_timeline["timeline_claims"]] == ["2027"]


def test_single_token_native_alias_is_allowed_but_single_token_name_is_not():
    quote = "Frontier has 1.4 GW of campus development capacity."
    raw = extract_customer_facts(quote, project_id="project-1", source=SOURCE)
    assert not scope_customer_facts(raw, "Frontier", source_text=quote)["capacity_claims"]
    assert scope_customer_facts(
        raw,
        "Frontier",
        source_text=quote,
        project_aliases=["Frontier"],
    )["capacity_claims"]


def test_duplicate_quote_occurrences_keep_each_original_offset_and_hash():
    quote = "Orion Data Center has 100 MW of IT load."
    text = f"## Orion Data Center\n{quote}\n## Orion Data Center update\n{quote}"
    binding = resolve_claim_subject(
        text,
        quote,
        project_name="Orion Data Center",
        source_hash=SOURCE["content_hash"],
    )

    assert binding is not None
    occurrences = binding["occurrences"]
    assert len(occurrences) == 2
    assert occurrences[0]["quote_span"] != occurrences[1]["quote_span"]
    assert all(item["source_hash"] == SOURCE["content_hash"] for item in occurrences)


def test_quote_offsets_are_unicode_codepoint_offsets():
    quote = "Orion Data Center has 100 MW of IT load."
    text = f"🛰️ Update. {quote}"
    binding = resolve_claim_subject(text, quote, project_name="Orion Data Center")

    assert binding is not None
    start, end = binding["occurrences"][0]["quote_span"]
    assert text[start:end] == quote


def _test_plan(project_id=None):
    block = {
        "block_id": "test-a",
        "load_scope_id": "load-a",
        "sequence_stage": "stage-1",
        "rating": "2",
        "unit": "MW",
        "rating_basis": "electrical_output",
        "installed_units": 4,
        "concurrent_units": 2,
        "test_fraction": "0.75",
    }
    if project_id is not None:
        block["project_id"] = project_id
    document = {
        "project_name": "Orion Data Center",
        "commissioning_test_plan": [block],
    }
    return f"Orion Data Center commissioning test plan.\n```json\n{json.dumps(document)}\n```"


def test_public_commissioning_plan_can_omit_private_uuid_after_native_site_match():
    text = _test_plan()
    result = extract_commissioning_plan(
        text,
        project_id="canonical-project-uuid",
        project_name="Orion Data Center",
        source=SOURCE,
    )

    assert len(result) == 1
    assert result[0]["project_id"] == "canonical-project-uuid"
    assert result[0]["evidence"]["rating"][0]["content_hash"] == SOURCE["content_hash"]
    assert result[0]["evidence"]["rating"][0]["quote"] in text


def test_public_commissioning_plan_cannot_supply_a_foreign_uuid():
    text = _test_plan("foreign-project-uuid")
    result = extract_commissioning_plan(
        text,
        project_id="canonical-project-uuid",
        project_name="Orion Data Center",
        source=SOURCE,
    )

    assert result[0]["invalid_reason"]


def test_public_commissioning_plan_must_name_a_native_project_site():
    result = extract_commissioning_plan(
        _test_plan(),
        project_id="canonical-project-uuid",
        project_name="Dallas Data Center",
        source=SOURCE,
        project_aliases=["Dallas Campus"],
    )

    assert result[0]["invalid_reason"]


def test_owner_membership_context_is_loaded_in_one_batch_query():
    class Session:
        calls = 0

        def execute(self, statement):
            self.calls += 1
            return []

    session = Session()
    project_ids = ["5e336d40-7b64-4d89-b0b2-5ee8c860ba15", "d321f5ca-6a2b-4d59-b908-952d07c1432b"]

    result = _verified_project_owner_names(session, project_ids)

    assert session.calls == 1
    assert result == {project_id: [] for project_id in project_ids}


def test_fact_free_source_skips_receipt_database_work_before_flush():
    class Session:
        def flush(self):
            raise AssertionError("fact-free source should skip the database")

        def execute(self, statement):
            raise AssertionError("fact-free source should skip the database")

    assert (
        persist_customer_facts(
            Session(),
            project_id="not-a-uuid-needed-for-prefilter",
            evidence_id="also-not-a-uuid",
            source_text="A company announced a new construction project.",
        )
        is None
    )


@pytest.mark.parametrize(
    "source_text",
    [
        "Orion Data Center has 100 MW of IT load.",
        '```json\n{"commissioning_test_plan": []}\n```',
        "Unknown " + "x" * 200_001,
    ],
    ids=["capacity-fact", "empty-engineering-plan", "oversized-source"],
)
def test_capacity_plan_or_overflow_source_does_not_skip_database_work(source_text):
    class VisitedDatabase(Exception):
        pass

    class Session:
        def flush(self):
            raise VisitedDatabase

    with pytest.raises(VisitedDatabase):
        persist_customer_facts(
            Session(),
            project_id="5e336d40-7b64-4d89-b0b2-5ee8c860ba15",
            evidence_id="d321f5ca-6a2b-4d59-b908-952d07c1432b",
            source_text=source_text,
        )
