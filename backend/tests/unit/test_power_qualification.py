"""Existing PRD gates: scoped reported facts, never model confidence or nameplate."""

import pytest

from gridlens.domain.power_qualification import qualify_official_power, qualify_retained_official

SITE = "811 Clayton Ln"
DEMAND = f"{SITE} construction requires 1 MW."
SUPPLY = f"Power supply for {SITE} construction is unavailable."
START = f"{SITE} construction starts between 2026-11-01 and 2026-11-05."
DURATION = f"{SITE} construction lasts 30 to 60 days."
GAP = (
    f"No suitable power supply is available for {SITE} construction "
    "throughout this start window and duration."
)
BUYER = f"The electrical contractor is responsible for power procurement for {SITE} construction."
CLAUSES = [DEMAND, SUPPLY, START, DURATION, GAP, BUYER]


def assess(text, **overrides):
    args = {
        "text": text,
        "site": SITE,
        "activity_key": "facility-expansion",
        "location": "Austin, TX",
    }
    return qualify_official_power(**(args | overrides))


def test_prospect_requires_separate_exact_activity_demand_and_supply():
    claim = assess(" ".join([DEMAND, SUPPLY]))
    assert claim["tier"] == "Prospect"
    assert claim["demand_quote"] == DEMAND
    assert claim["supply_quote"] == SUPPLY
    assert "qualified_remaining_gap" not in claim


@pytest.mark.parametrize("omit", range(6))
def test_each_lead_gate_is_mandatory(omit):
    claim = assess(" ".join(c for i, c in enumerate(CLAUSES) if i != omit))
    assert claim.get("tier") == (None if omit in {0, 1} else "Prospect")


def test_full_lead_keeps_quotes_and_conservative_interval_arithmetic():
    claim = assess(" ".join(CLAUSES))
    assert claim["tier"] == "Lead"
    assert claim["start_quote"] == START
    assert claim["duration_quote"] == DURATION
    assert claim["buyer_quote"] == BUYER
    assert claim["buying_role"] == "electrical contractor"
    gap = claim["qualified_remaining_gap"]
    assert gap["required_mw_min"] == gap["remaining_mw_min"] == "1"
    assert gap["required_mw_max"] == gap["remaining_mw_max"] == "1"
    assert gap["available_mw_min"] == gap["available_mw_max"] == "0"
    assert gap["basis_quote"] == GAP
    assert gap["value_kind"] == "Derived"


@pytest.mark.parametrize(
    ("old", "new", "tier"),
    [
        ("requires 1 MW", "requires 0 MW", None),
        ("requires 1 MW", "requires 0.5 to 1.5 MW", "Lead"),
        ("requires 1 MW", "requires 2 to 1 MW", None),
        ("requires 1 MW", "requires approximately 1 MW", None),
        ("requires 1 MW", "campus capacity is 100 MW", None),
        ("requires 1 MW", "generator nameplate is 1 MW", None),
        ("is unavailable", "is unknown", None),
        ("is unavailable", "is adequate", None),
        ("is unavailable", "is not delayed", None),
        ("is unavailable", "might be unavailable", None),
        (START, START.replace("2026-11-05", "2026-02-31"), "Prospect"),
        (START, START.replace("2026-11-05", "2026-10-05"), "Prospect"),
        ("lasts 30 to 60", "lasts 60 to 30", "Prospect"),
        ("lasts 30 to 60 days", "lasts up to 60 days", None),
        (GAP, GAP.replace("No suitable power supply", "Permanent utility service"), "Prospect"),
        (SUPPLY, SUPPLY.replace(SITE, "Other Site"), None),
        (SUPPLY, SUPPLY.replace("construction", "commissioning"), None),
        (BUYER, BUYER.replace(SITE, "Other Site"), "Prospect"),
    ],
)
def test_negative_and_range_boundaries(old, new, tier):
    assert assess(" ".join(CLAUSES).replace(old, new)).get("tier") == tier


@pytest.mark.parametrize(
    "extra",
    [
        f"Power supply for {SITE} construction is available.",
        f"Utility service for {SITE} construction is now sufficient.",
        "The power package is fully awarded.",
        "The required construction power is secured.",
        "Adequate temporary power supply is available.",
        "The construction scope is completed.",
        DEMAND,
        SUPPLY,
    ],
)
def test_contradictions_and_duplicate_ambiguous_claims_do_not_promote(extra):
    assert assess(" ".join([*CLAUSES, extra])) == {}


@pytest.mark.parametrize(
    "overrides", [{"site": "Other Site"}, {"location": None}, {"activity_key": "commissioning"}]
)
def test_wrong_site_missing_location_or_different_activity_never_qualifies(overrides):
    assert assess(" ".join(CLAUSES), **overrides) == {}


def test_native_field_binding_rejects_ambiguous_or_missing_site():
    native = f"description: {' '.join(CLAUSES)}\naddress: {SITE}"
    assert qualify_retained_official(native, "facility-expansion", "Austin, TX")["tier"] == "Lead"
    assert (
        qualify_retained_official(native + "\naddress: Other Site", "facility-expansion", "TX")
        == {}
    )
    assert qualify_retained_official(" ".join(CLAUSES), "facility-expansion", "TX") == {}


@pytest.mark.parametrize(
    "context",
    [
        "Hypothetical scenario.",
        "Example permit language.",
        "Template for applicants.",
        "Quoted statements follow.",
        "Historical project scope.",
        "2021 project scope.",
        "As of 2021.",
        "If this package proceeds.",
        "Assuming funding is approved.",
        "Proposed requirements.",
        '"Illustrative quotation."',
    ],
)
def test_nonfactual_or_historical_context_cannot_launder_exact_gate_clauses(context):
    assert assess(context + " " + " ".join(CLAUSES)) == {}
    assert assess(" ".join(CLAUSES) + " " + context) == {}


def test_unbounded_numeric_source_text_does_not_overflow_or_promote():
    oversized = "9" * 5000
    assert assess(" ".join(CLAUSES).replace("requires 1 MW", f"requires {oversized} MW")) == {}
    claim = assess(" ".join(CLAUSES).replace("lasts 30 to 60", f"lasts 30 to {oversized}"))
    assert claim["tier"] == "Prospect"


@pytest.mark.parametrize(
    ("required", "available", "tier", "remaining"),
    [
        ("1 to 2", "0.2 to 0.4", "Lead", ("0.6", "1.8")),
        ("1", "0.25", "Lead", ("0.75", "0.75")),
        ("1", "0", "Lead", ("1", "1")),
        ("1 to 2", "1.5", "Prospect", None),
        ("1", "1", "Signal", None),
        ("1", "2", "Signal", None),
        ("1", "0.5 to 0.2", "Prospect", None),
    ],
)
def test_exact_aggregate_interval_supply_arithmetic(required, available, tier, remaining):
    supply = (
        f"Total suitable power supply available for {SITE} construction is {available} MW "
        "throughout this start window and duration."
    )
    text = " ".join(CLAUSES).replace("requires 1 MW", f"requires {required} MW")
    text = text.replace("is unavailable", "is insufficient").replace(GAP, supply)
    claim = assess(text)
    assert claim["tier"] == tier
    if remaining:
        gap = claim["qualified_remaining_gap"]
        assert (gap["remaining_mw_min"], gap["remaining_mw_max"]) == remaining
        assert gap["basis_quote"] == supply
    elif tier == "Signal":
        assert claim["qualification_conflict"] is True


@pytest.mark.parametrize(
    "replacement",
    [
        "Total proposed power supply available",
        "Generator nameplate power supply available",
        "Total suitable power supply available for Other Site construction is 0.2 MW",
        "Total suitable power supply available for 811 Clayton Ln commissioning is 0.2 MW",
    ],
)
def test_nonzero_supply_cannot_borrow_authority_or_activity(replacement):
    supply = (
        f"Total suitable power supply available for {SITE} construction is 0.2 MW "
        "throughout this start window and duration."
    )
    changed = supply.replace(
        f"Total suitable power supply available for {SITE} construction is 0.2 MW", replacement
    )
    claim = assess(
        " ".join(CLAUSES).replace("is unavailable", "is insufficient").replace(GAP, changed)
    )
    assert claim.get("tier") != "Lead"


def test_partial_supply_interval_and_multiple_supply_options_cannot_qualify_lead():
    supply = (
        f"Total suitable power supply available for {SITE} construction is 0.2 MW "
        "throughout this start window and duration."
    )
    text = " ".join(CLAUSES).replace("is unavailable", "is insufficient").replace(GAP, supply)
    for changed in [
        text.replace("throughout this start window and duration", "during the first week"),
        text + " " + supply,
        text + " " + GAP,
    ]:
        assert assess(changed)["tier"] == "Prospect"
