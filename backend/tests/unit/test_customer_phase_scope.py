"""Phase qualifiers must not promote a scoped amount into a full-site claim."""

from datetime import date

import pytest

from gridlens.domain.customer_intelligence import (
    extract_customer_facts,
    resolve_customer_intelligence,
)
from gridlens.intelligence.customer_intelligence import scope_customer_facts

SOURCE = {
    "url": "https://owner.example/alpha",
    "evidence_id": "phase-evidence",
    "content_hash": "a" * 64,
    "published_at": "2026-10-01",
    "observed_at": "2026-11-12T00:00:00Z",
    "authority": "primary",
    "verification_status": "verified",
}


def raw(text):
    return extract_customer_facts(text, project_id="alpha", source=SOURCE)


@pytest.mark.parametrize("phase", ["Phase 2", "Phase A", "initial phase", "Phase II"])
def test_postfix_phase_capacity_abstains_in_raw_extraction(phase):
    assert raw(f"Alpha campus has 100 MW of IT capacity for {phase}.")["capacity_claims"] == []


@pytest.mark.parametrize("phase", ["Phase 2", "Phase A", "initial phase", "Phase II"])
def test_postfix_phase_capacity_cannot_pass_runtime_project_scope(phase):
    payload = scope_customer_facts(
        raw(f"Alpha campus has 100 MW of IT capacity for {phase}."), "Alpha campus"
    )
    assert payload["capacity_claims"] == []
    result = resolve_customer_intelligence(
        [{"project_id": "alpha", "facts": [payload]}], as_of=date(2026, 11, 12)
    )
    assert result["capacity"]["total_mw"] is None


@pytest.mark.parametrize("phase", ["Phase A", "Phase A-1", "unidentified phase"])
def test_unrecognized_phase_context_abstains_instead_of_defaulting_to_site(phase):
    assert raw(f"Alpha campus {phase} has 100 MW of IT capacity.")["capacity_claims"] == []


def test_known_prefix_phase_capacity_remains_partial_through_runtime_guard():
    payload = scope_customer_facts(
        raw("Alpha campus Phase 2 has 100 MW of IT capacity."), "Alpha campus"
    )
    assert len(payload["capacity_claims"]) == 1
    claim = payload["capacity_claims"][0]
    assert claim["scope_id"] == "alpha:phase:2"
    assert claim["capacity_type"] == "individual_phase"
    result = resolve_customer_intelligence(
        [{"project_id": "alpha", "facts": [payload]}], as_of=date(2026, 11, 12)
    )
    assert result["capacity"]["totals"][0]["complete"] is False
    assert result["capacity"]["total_mw"] is None


def test_explicit_across_all_campus_total_survives_phase_qualifiers():
    payload = scope_customer_facts(
        raw(
            "Alpha campus has critical IT power increasing in Phase 2 for a total of "
            "480MW across all 8 buildings."
        ),
        "Alpha campus",
    )
    assert len(payload["capacity_claims"]) == 1
    claim = payload["capacity_claims"][0]
    assert (claim["scope_id"], claim["value_mw"]) == ("alpha:site", "480")
    assert claim["includes_scope_ids"] == ["alpha:phase:2"]
