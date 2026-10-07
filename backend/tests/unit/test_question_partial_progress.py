from gridlens.intelligence.autonomous_research import _question_partial_progress


def card(**fields):
    return {
        "research_state": {
            name: {"status": status, "claims": [{"evidence_id": "retained"}]}
            for name, status in fields.items()
        }
    }


def test_supply_progress_requires_new_supported_exact_component_without_regression():
    empty = card()
    service = card(permanent_service="SUPPORTED")
    both = card(permanent_service="SUPPORTED", supply_adequacy="SUPPORTED")
    assert _question_partial_progress("supply", empty, service, {})
    assert not _question_partial_progress("supply", service, service, {})
    assert not _question_partial_progress("supply", service, both, {})
    assert not _question_partial_progress("supply", service, card(supply_adequacy="SUPPORTED"), {})
    service["research_state"]["permanent_service"]["claims"] = []
    assert not _question_partial_progress("supply", empty, service, {})


def test_conflict_progress_only_counts_original_fields():
    before = card(phase="CONFLICT", supply_adequacy="CONFLICT")
    context = {"conflict_fields": ["phase", "supply_adequacy"]}
    after = card(phase="SUPPORTED", supply_adequacy="CONFLICT")
    assert _question_partial_progress("conflict", before, after, context)
    assert not _question_partial_progress(
        "conflict", before, card(activity_load_mw="SUPPORTED"), context
    )


def test_accepted_unrelated_evidence_and_construction_do_not_partially_resolve_commissioning():
    before = card()
    after = card(phase="SUPPORTED", activity_load_mw="SUPPORTED")
    after["research_state"]["phase"]["value"] = "construction_active"
    assert not _question_partial_progress("commissioning", before, after, {})
    assert not _question_partial_progress("buyer", before, after, {})
    assert not _question_partial_progress("supply", before, after, {})
