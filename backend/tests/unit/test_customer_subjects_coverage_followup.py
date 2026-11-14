"""Bounded coverage regressions for source-local expansion claims."""

import json
from pathlib import Path

from gridlens.domain.customer_intelligence import extract_customer_facts
from gridlens.domain.customer_subjects import resolve_claim_subject
from gridlens.intelligence.customer_intelligence import scope_customer_facts

SOURCE = {
    "url": "https://owner.example/project-update",
    "evidence_id": "subject-evidence",
    "content_hash": "d" * 64,
    "published_at": "2024-03-26",
    "observed_at": "2026-11-12T00:00:00Z",
    "authority": "unknown",
    "verification_status": "reported",
}


def _scope(text: str, *, aliases: list[str] = (), project_name: str = "SVY01") -> dict:
    raw = extract_customer_facts(text, project_id="project-1", source=SOURCE)
    return scope_customer_facts(
        raw,
        project_name,
        source_text=text,
        project_aliases=aliases,
    )


def test_retained_stack_expansion_binds_only_with_source_native_site_alias():
    fixture = (
        Path(__file__).resolve().parents[3]
        / "eval"
        / "customer-commercial-v1"
        / "sources"
        / "stack.json"
    )
    source = json.loads(fixture.read_text(encoding="utf-8"))
    text = "\n\n".join(source["excerpts"])
    raw = extract_customer_facts(text, project_id="project-1", source=SOURCE)
    candidates = [claim for claim in raw["capacity_claims"] if claim["value_mw"] == "60"]

    assert len(candidates) == 1
    assert candidates[0]["basis"] == "campus_development"
    assert candidates[0]["scope_id"] == "project-1:expansion"
    assert candidates[0]["quote"] == (
        "The 60MW data center expansion will provide critical capacity and scale to one of "
        "the largest and most desired data center markets in the world."
    )

    # SVY01 is a source-native code in the retained text, supplied as an existing
    # native alias. It is not taken from the V1 reference label.
    scoped = scope_customer_facts(
        raw,
        "SVY01",
        source_text=text,
        project_aliases=["SVY01"],
    )
    claims = [claim for claim in scoped["capacity_claims"] if claim["value_mw"] == "60"]
    assert len(claims) == 1
    binding = claims[0]["subject_binding"]
    assert binding["subject_kind"] == "adjacent_anaphora"
    assert binding["alias"] == "SVY01"
    assert (
        text[
            binding["occurrences"][0]["quote_span"][0] : binding["occurrences"][0]["quote_span"][1]
        ]
        == claims[0]["quote"]
    )


def test_expansion_anaphora_requires_immediate_unique_source_site():
    text = (
        "The 100 MW data center campus in Reno, North Site was announced. "
        "The 60 MW data center expansion will provide critical capacity."
    )
    raw = extract_customer_facts(text, project_id="project-1", source=SOURCE)
    claim = next(claim for claim in raw["capacity_claims"] if claim["value_mw"] == "60")
    binding = resolve_claim_subject(
        text,
        claim["quote"],
        project_name="North Site",
        project_aliases=["North Site"],
    )
    assert binding is not None
    assert binding["subject_kind"] == "adjacent_anaphora"
    assert binding["alias"] == "North Site"


def test_expansion_anaphora_refuses_second_site_and_unrelated_intervening_clause():
    second_site = (
        "The 100 MW campus in Reno, North Site is planned adjacent to South Campus. "
        "The 60 MW data center expansion will provide critical capacity."
    )
    separated = (
        "The 100 MW data center campus in Reno, North Site was announced. "
        "A separate market update follows. "
        "The 60 MW data center expansion will provide critical capacity."
    )
    for text in (second_site, separated):
        raw = extract_customer_facts(text, project_id="project-1", source=SOURCE)
        claim = next(claim for claim in raw["capacity_claims"] if claim["value_mw"] == "60")
        assert (
            resolve_claim_subject(
                text,
                claim["quote"],
                project_name="North Site",
                project_aliases=["North Site"],
            )
            is None
        )


def test_expansion_anaphora_refuses_foreign_site_relations():
    text = (
        "The 100 MW data center campus in Reno, North Site was announced. "
        "The expansion at South Campus has 60 MW of critical IT load."
    )
    claim = extract_customer_facts(text, project_id="project-1", source=SOURCE)["capacity_claims"][
        -1
    ]
    assert (
        resolve_claim_subject(
            text,
            claim["quote"],
            project_name="North Site",
            project_aliases=["North Site"],
        )
        is None
    )


def test_expansion_basis_and_allocation_adversaries_remain_abstentions():
    basis_ambiguous = (
        "The 60 MW expansion may refer to either IT load or utility service; "
        "no campus development amount is stated."
    )
    offtake = "The 400 MW data center expansion is contracted offtake, not facility capacity."
    option = "The 150 MW data center expansion is only an option under a lease agreement."

    for text in (basis_ambiguous, offtake, option):
        assert (
            extract_customer_facts(text, project_id="project-1", source=SOURCE)["capacity_claims"]
            == []
        )


def test_unrelated_expansion_word_does_not_create_campus_capacity():
    text = "The company announced a 60 MW expansion in its contracted service footprint."
    assert (
        extract_customer_facts(text, project_id="project-1", source=SOURCE)["capacity_claims"] == []
    )
