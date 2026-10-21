from datetime import date
from uuid import UUID, uuid4

import pytest

from gridlens.domain.commercial_triage import (
    build_card,
    cards,
    group_cards,
    grouped_need_ids,
    surfaced_on,
)
from gridlens.domain.pursuits import CommercialTriageHistoryVersion
from gridlens.ingestion.adapters.retained_document import SOURCES


def _item(**overrides):
    item = {
        "id": uuid4(),
        "project_id": uuid4(),
        "name": "Ellenwood data center",
        "location": "Ellenwood, Georgia",
        "tier": "Signal",
        "activity": "electrical-construction",
        "asset_type": "data_center",
        "lifecycle_state": "electrical_buildout",
        "lifecycle_timeline": [],
        "required_mw": None,
        "start_window": None,
        "duration": None,
        "supply": "Unknown",
        "conflict_state": "Not assessed",
        "missing_facts": ["activity-specific power requirement", "buyer or responsible operator"],
        "supported_action": (
            "Install new substation transformers for data center electrical construction"
        ),
        "signal_display_decision": "REVIEW",
        "evidence": [
            {
                "id": uuid4(),
                "title": "Current EPD substation permit",
                "abstract": (
                    "Install new substation transformers for data center electrical construction."
                ),
                "url": "https://example.test/permit",
                "content_hash": "a" * 64,
                "event_date": "2026-10-01",
                "source_id": "georgia-air-draft-title-v",
                "document_number": "30104",
            }
        ],
    }
    item.update(overrides)
    return item


def _f17_stack_item():
    record = _item(
        name="SVY02A / Memorex Junction data center",
        location="1200 Memorex Drive, Santa Clara, CA",
        asset_type=None,
        activity="utility-service",
        lifecycle_state="paused",
        supported_action=None,
        missing_facts=[],
        required_mw=1,
        start_window="2027",
        duration="1 year",
        supply="Reported supply",
    )
    record["evidence"] = []
    for source_id, abstract in (
        (
            "f17-stack-city-claim",
            "At 1200 Memorex Drive in Santa Clara, STACK reported an 18 MVA cap until "
            "at least 2028, against an earlier 28MVA 2026 and 31MVA 2027 schedule.",
        ),
        (
            "f17-stack-cec-filing",
            "At 1200 Memorex Drive in Santa Clara, STACK's draft Table E1 available "
            "capacity schedule (MVA) lists 28 for 2026 and 31 for 2027.",
        ),
    ):
        policy = SOURCES[source_id]
        record["evidence"].append(
            {
                "id": uuid4(),
                "source_id": source_id,
                "url": policy["url"],
                "content_hash": policy["sha256"],
                "abstract": abstract,
                "title": "Retained source excerpt",
                "assessment_current": True,
            }
        )
    return record


def test_f17_stack_watch_surfaces_attributed_conflict_and_verification_action():
    record = _f17_stack_item()
    card = build_card(record, None, date(2026, 10, 21))

    assert card["disposition"] == "WATCH"
    assert "STACK's June 24, 2024 city claim reports" in card["reason"]
    assert "28 MVA (2026) / 31 MVA (2027)" in card["reason"]
    assert "September 2021 draft Substation Agreement" in card["reason"]
    assert "attached to STACK's February 2025 CEC filing" in card["reason"]
    assert "SVP told STACK on March 14, 2024" in card["reason"]
    assert "not an adjudicated" in card["reason"]
    assert "temporary-power need remains UNKNOWN" in card["reason"]
    assert "Verify the current utility delivery schedule" in card["next_action"]
    assert "temporary-power scope" in card["next_action"]
    assert {source["url"] for source in card["sources"]} == {
        SOURCES["f17-stack-city-claim"]["url"],
        SOURCES["f17-stack-cec-filing"]["url"],
    }
    assert card["required_mw"] == record["required_mw"]
    assert card["start_window"] == record["start_window"]
    assert card["duration"] == record["duration"]
    assert card["supply"] == record["supply"]


@pytest.mark.parametrize(
    "mutation", ["missing", "stale", "wrong_hash", "wrong_url", "wrong_site", "wrong_alias"]
)
def test_f17_stack_narrative_falls_back_without_exact_current_sources(mutation):
    record = _f17_stack_item()
    if mutation == "missing":
        record["evidence"].pop()
    elif mutation == "stale":
        record["evidence"][1]["assessment_current"] = False
    elif mutation == "wrong_hash":
        record["evidence"][1]["content_hash"] = "0" * 64
    elif mutation == "wrong_url":
        record["evidence"][1]["url"] = "https://example.test/cec"
    elif mutation == "wrong_alias":
        record["name"] = "SVY02A / Another Project data center"
    else:
        record["location"] = "1200 Other Street, Santa Clara, CA"

    card = build_card(record, None, date(2026, 10, 21))
    assert card["disposition"] == "WATCH"
    assert "STACK's city claim reports" not in card["reason"]
    assert "Verify the current utility delivery schedule" not in card["next_action"]


def test_power_schedule_refs_do_not_change_commercial_research_fingerprint():
    base = _item()
    legacy_ref = {
        "need_id": str(base["id"]),
        "fact_version_id": str(uuid4()),
        "content_hash": "a" * 64,
        "authority": "User-confirmed",
        "fact_type": "demand",
        "value": {"mw": "5"},
    }
    schedule_ref = {
        "need_id": str(base["id"]),
        "fact_version_id": str(uuid4()),
        "content_hash": "b" * 64,
        "authority": "User-confirmed",
        "fact_type": "power_schedule",
        "value": {"phases": []},
    }
    no_facts = build_card(base, {}, date(2026, 10, 21))
    demand = build_card({**base, "operator_fact_refs": [legacy_ref]}, {}, date(2026, 10, 21))
    demand_and_schedule = build_card(
        {**base, "operator_fact_refs": [legacy_ref, schedule_ref]}, {}, date(2026, 10, 21)
    )
    schedule_only = build_card(
        {**base, "operator_fact_refs": [schedule_ref]}, {}, date(2026, 10, 21)
    )

    assert demand["input_hash"] != no_facts["input_hash"]
    assert demand_and_schedule["input_hash"] == demand["input_hash"]
    assert schedule_only["input_hash"] == no_facts["input_hash"]
    assert all(
        set(reference) == {"need_id", "fact_version_id", "content_hash", "authority"}
        for reference in demand_and_schedule["operator_fact_refs"]
    )


def test_permit_contact_is_action_now_with_unknown_need_and_no_inferred_company():
    item = _item()
    evidence_id = str(uuid4())
    chain = {
        "candidates": [],
        "permit_summaries": [
            {
                "evidence_id": evidence_id,
                "url": "https://example.test/permit",
                "facts": [
                    {"label": "Permit contractor trade", "value": "Electrician"},
                    {"label": "Permit-listed contractor name", "value": "Blake Combs"},
                    {"label": "Contractor phone", "value": "555-0100"},
                ],
            }
        ],
    }
    card = build_card(item, chain, date(2026, 10, 3))
    assert card["disposition"] == "ACTION NOW"
    assert card["required_mw"] is None
    assert card["contacts"][0]["organization"] is None
    assert card["contacts"][0]["person"] == "Blake Combs"
    assert "unverified" in card["contacts"][0]["role"]
    assert "construction not established" in card["stage"]["stage"]
    assert "campus" not in card["hypothesis"].casefold()


def test_grouped_need_id_seam_pages_after_merging_same_work_siblings():
    items = []
    for index in range(54):
        item_id = UUID(int=index + 1)
        item = _item(id=item_id, project_id=item_id)
        item["evidence"][0]["document_number"] = f"permit-{index}"
        items.append(item)
    sibling = items[-1]
    sibling["evidence"][0]["document_number"] = items[0]["evidence"][0]["document_number"]
    sibling["signal_display_decision"] = "REVIEW"
    items[0]["signal_display_decision"] = "HOLD"

    expected = grouped_need_ids(items, limit=50)
    cards_page = cards(items, {}, date(2026, 10, 7), limit=50)

    assert len(expected) == len(cards_page) == 50
    assert expected == [card["related_need_ids"] for card in cards_page]
    assert expected[0] == sorted([str(items[0]["id"]), str(sibling["id"])])
    assert len({need_id for group in expected for need_id in group}) == 51


def test_user_fact_hash_is_optional_and_group_provenance_stays_need_scoped():
    first_id = UUID(int=8001)
    second_id = UUID(int=8002)
    first = _item(id=first_id, project_id=first_id)
    second = _item(id=second_id, project_id=second_id)
    second["evidence"][0]["document_number"] = first["evidence"][0]["document_number"]

    no_fact = build_card(first, None, date(2026, 10, 7))
    explicit_no_fact = build_card({**first, "operator_fact_refs": []}, None, date(2026, 10, 7))
    first_ref = {
        "need_id": str(first_id),
        "fact_version_id": str(UUID(int=8101)),
        "content_hash": "a" * 64,
        "authority": "User-confirmed",
    }
    second_ref = {
        "need_id": str(second_id),
        "fact_version_id": str(UUID(int=8102)),
        "content_hash": "b" * 64,
        "authority": "User-confirmed",
    }
    first["operator_fact_refs"] = [first_ref]
    second["operator_fact_refs"] = [second_ref]
    grouped_card = group_cards([first, second], {}, date(2026, 10, 7))[0]

    assert no_fact["input_hash"] == explicit_no_fact["input_hash"]
    assert "operator_fact_refs" not in explicit_no_fact
    assert grouped_card["input_hash"] != no_fact["input_hash"]
    assert grouped_card["operator_fact_refs"] == [first_ref, second_ref]
    assert all("value" not in reference for reference in grouped_card["operator_fact_refs"])
    legacy_version = CommercialTriageHistoryVersion.model_validate(
        {
            "version": 1,
            "disposition": "RESEARCH",
            "snapshot_status": "saved_as_of",
        }
    )
    assert legacy_version.operator_fact_provenance == "legacy_unknown"


def test_contractor_is_not_rejected_as_rental_intermediary_and_hold_routes_to_research():
    item = _item(signal_display_decision="HOLD", signal_display_reason="Need scope is unclear")
    chain = {
        "candidates": [
            {
                "organization": "Electrical Builder LLC",
                "category": "electrical_contractor",
                "organization_relationship": "UNKNOWN",
                "reason": "Permit-listed electrical contractor",
                "stale": False,
                "evidence": [],
                "public_contacts": [],
            }
        ],
        "permit_summaries": [],
    }
    card = build_card(item, chain, date(2026, 10, 3))
    assert card["disposition"] == "RESEARCH"
    assert "intermediaries only" not in card["reason"]


def test_rental_intermediary_is_excluded_even_when_relationship_is_direct():
    item = _item()
    intermediary = {
        "organization": "Metro Equipment Rentals",
        "category": "owner_developer",
        "organization_relationship": "DIRECT",
        "reason": "Permit-listed organization",
        "stale": False,
        "evidence": [],
        "public_contacts": [{"kind": "phone", "value": "555-0104"}],
    }
    rental_summary = {
        "evidence_id": str(uuid4()),
        "url": "https://example.test/rental",
        "facts": [
            {"label": "Permit contractor organization", "value": "Metro Equipment Rentals"},
            {"label": "Contractor phone", "value": "555-0104"},
        ],
    }
    rejected = build_card(
        item,
        {"candidates": [intermediary], "permit_summaries": [rental_summary]},
        date(2026, 10, 3),
    )
    assert rejected["disposition"] == "REJECT"
    assert all("Rentals" not in str(contact["organization"]) for contact in rejected["contacts"])

    owner = {
        **intermediary,
        "organization": "Campus Owner LLC",
        "public_contacts": [{"kind": "phone", "value": "555-0105"}],
    }
    mixed = build_card(
        item,
        {"candidates": [intermediary, owner], "permit_summaries": [rental_summary]},
        date(2026, 10, 3),
    )
    assert mixed["disposition"] == "ACTION NOW"
    assert all("Rentals" not in str(contact["organization"]) for contact in mixed["contacts"])


def test_superseded_temporary_scope_does_not_make_current_routine_permit_actionable():
    item = _item(
        evidence=[
            {
                "id": uuid4(),
                "title": "Old temporary service permit",
                "abstract": "Temporary generator service for construction power.",
                "url": "https://example.test/old",
                "content_hash": "f" * 64,
                "event_date": date(2025, 1, 1),
                "source_id": "austin-building-permits",
                "document_number": "2025-111111 EP",
                "assessment_current": False,
            },
            {
                "id": uuid4(),
                "title": "Current routine tenant permit",
                "abstract": "Ordinary interior tenant finish work.",
                "url": "https://example.test/current",
                "content_hash": "e" * 64,
                "event_date": date(2026, 9, 1),
                "source_id": "austin-building-permits",
                "document_number": "2026-111111 EP",
                "assessment_current": True,
            },
        ]
    )
    card = build_card(item, None, date(2026, 10, 3))
    assert card["disposition"] != "ACTION NOW"
    assert all(fact["url"] != "https://example.test/old" for fact in card["facts"])


def test_campus_nameplate_does_not_fill_need_mw_and_question_is_specific():
    item = _item(
        supported_action="The campus has 100 MW of nameplate capacity.",
        evidence=[
            {
                "id": uuid4(),
                "title": "Campus capacity filing",
                "abstract": "The campus has 100 MW of nameplate capacity.",
                "url": "https://example.test/campus",
                "content_hash": "b" * 64,
                "event_date": "2026-10-01",
                "source_id": "georgia-air-draft-title-v",
                "document_number": "30104",
            }
        ],
    )
    card = build_card(item, None, date(2026, 10, 3))
    assert card["required_mw"] is None
    assert "energization" in card["next_question"]
    assert "100 MW" not in card["hypothesis"]


def test_conflict_is_research_and_watch_has_cited_concrete_source_event():
    conflicted = build_card(_item(conflict_state="unresolved conflict"), None, date(2026, 10, 3))
    assert conflicted["disposition"] == "RESEARCH"
    watch_item = _item(
        name="Unknown equipment permit",
        asset_type="unknown",
        lifecycle_state="permitting",
        missing_facts=[],
        supported_action=None,
    )
    watched = build_card(watch_item, None, date(2026, 10, 3))
    assert watched["disposition"] == "WATCH"
    assert watched["watch"]["source_url"] == "https://example.test/permit"
    assert "Observe a dated EPC award" in watched["watch"]["event"]
    assert watched["watch"]["date"] is None


def test_explicit_closed_permanent_supply_and_backup_only_scope_reject_but_unknown_stays_open():
    closed = _item()
    card = build_card(
        closed,
        {
            "candidates": [],
            "permit_summaries": [
                {
                    "evidence_id": str(uuid4()),
                    "url": "https://example.test/closed",
                    "facts": [{"label": "Permit status", "value": "Withdrawn"}],
                }
            ],
        },
        date(2026, 10, 3),
    )
    assert card["disposition"] == "REJECT"
    assert "status says" in card["reason"]

    permanent = _item(
        supported_action="Permanent utility service is adequate for the facility.",
        evidence=[
            {
                "id": uuid4(),
                "title": "Utility service review",
                "abstract": "Permanent utility supply is adequate for the facility.",
                "url": "https://example.test/utility",
                "content_hash": "9" * 64,
                "event_date": "2026-10-01",
            }
        ],
    )
    assert build_card(permanent, None, date(2026, 10, 3))["disposition"] == "REJECT"

    backup_only = _item(
        supported_action="Replace backup generator as routine maintenance.",
        evidence=[
            {
                "id": uuid4(),
                "title": "Backup generator replacement",
                "abstract": "Routine backup generator replacement; no temporary service.",
                "url": "https://example.test/backup",
                "content_hash": "8" * 64,
                "event_date": "2026-10-01",
            }
        ],
    )
    assert build_card(backup_only, None, date(2026, 10, 3))["disposition"] == "REJECT"

    unknown = _item(
        signal_display_decision="HOLD",
        signal_display_reason="No need-specific demand evidence.",
        evidence=[
            {
                "id": uuid4(),
                "title": "Unresolved project scope",
                "abstract": "The current filing does not report project power requirements.",
                "url": "https://example.test/unknown",
                "content_hash": "7" * 64,
                "event_date": "2026-10-01",
            }
        ],
    )
    assert build_card(unknown, None, date(2026, 10, 3))["disposition"] == "RESEARCH"


def test_exact_austin_permit_case_grouping_preserves_need_ids_and_sibling_evidence_hash():
    project_id = uuid4()
    first = _item(
        project_id=project_id, asset_type="unknown", name="Same work", activity="temporary-power"
    )
    second = _item(
        project_id=uuid4(), asset_type="unknown", name="Same work", activity="temporary-power"
    )
    for item, suffix, digest in ((first, "BP", "c"), (second, "EP", "d")):
        item["evidence"][0].update(
            source_id="austin-building-permits",
            document_number=f"2019-123456 {suffix}",
            content_hash=digest * 64,
            title="Temporary power permit",
            abstract="Temporary service construction power.",
        )
    result = cards([first, second], {}, date(2026, 10, 3), 50)
    assert len(result) == 1
    assert set(result[0]["related_need_ids"]) == {str(first["id"]), str(second["id"])}
    assert set(result[0]["related_project_ids"]) == {
        str(project_id),
        str(second["project_id"]),
    }
    assert len(result[0]["facts"]) == 2
    assert len(result[0]["input_hash"]) == 64
    original_hash = result[0]["input_hash"]
    second["evidence"][0]["content_hash"] = "e" * 64
    changed = cards([first, second], {}, date(2026, 10, 3), 50)
    assert changed[0]["input_hash"] != original_hash


@pytest.mark.parametrize("sibling_state", ["closed", "held", "conflict"])
def test_same_work_contradiction_is_research_and_order_independent(sibling_state):
    action = _item()
    sibling = _item(project_id=uuid4())
    for item, suffix in ((action, "BP"), (sibling, "EP")):
        item["evidence"][0].update(
            source_id="austin-building-permits",
            document_number=f"2019-123456 {suffix}",
            content_hash=("a" if suffix == "BP" else "b") * 64,
            title="Temporary data-center construction service",
            abstract="Temporary service for data-center construction work.",
        )
    if sibling_state == "closed":
        sibling["evidence"][0]["permit_status"] = "Closed"
    elif sibling_state == "held":
        sibling["signal_display_decision"] = "HOLD"
        sibling["signal_display_reason"] = "Resolve the project scope."
    else:
        sibling["conflict_state"] = "Unresolved conflict"

    chains = {
        str(item["project_id"]): {
            "candidates": [],
            "permit_summaries": [
                {
                    "evidence_id": str(item["evidence"][0]["id"]),
                    "url": item["evidence"][0]["url"],
                    "facts": [
                        {"label": "Contractor organization", "value": "Orion Electric"},
                        {"label": "Contractor phone", "value": "555-0100"},
                    ],
                }
            ],
        }
        for item in (action, sibling)
    }
    forward = cards([action, sibling], chains, date(2026, 10, 3), 50)
    reverse = cards([sibling, action], chains, date(2026, 10, 3), 50)
    assert forward == reverse
    assert len(forward) == 1
    card = forward[0]
    assert card["disposition"] == "RESEARCH"
    assert (
        "contradictory" in card["reason"].casefold()
        or "different states" in card["reason"].casefold()
    )
    assert {state["disposition"] for state in card["related_need_states"]} == {
        "ACTION NOW",
        "REJECT" if sibling_state == "closed" else "RESEARCH",
    }
    assert set(card["related_need_ids"]) == {str(action["id"]), str(sibling["id"])}


def test_dc_construction_ranks_before_generic_permit_and_role_only_is_not_action_now():
    generic = _item(
        name="Austin temp permit",
        location="Austin, TX",
        asset_type="unknown",
        activity="temporary-power",
        supported_action="Temporary service for construction power.",
        evidence=[
            {
                "id": uuid4(),
                "title": "Austin permit temporary service",
                "abstract": "Temporary service for construction power.",
                "url": "https://example.test/temp",
                "content_hash": "1" * 64,
                "source_id": "austin-building-permits",
                "document_number": "2026-123456 EP",
            }
        ],
    )
    data_center = _item(
        name="Data center construction",
        location="Chicago, IL",
        supported_action="New data center construction includes transformer installation.",
        evidence=[
            {
                "id": uuid4(),
                "title": "Electrical Permit",
                "abstract": "New data center construction includes transformer installation.",
                "url": "https://example.test/dc",
                "content_hash": "2" * 64,
                "source_id": "chicago-building-permits",
                "document_number": "3451848",
            }
        ],
    )
    order = cards([generic, data_center], {}, date(2026, 10, 3), 50)
    assert order[0]["id"] == str(data_center["id"])

    role_only = build_card(
        data_center,
        {
            "candidates": [],
            "permit_summaries": [
                {
                    "evidence_id": str(uuid4()),
                    "url": "https://example.test/dc",
                    "facts": [
                        {"label": "Permit contractor trade", "value": "Electrical Contractor"}
                    ],
                }
            ],
        },
        date(2026, 10, 3),
    )
    assert role_only["disposition"] == "RESEARCH"
    assert "temporary construction or commissioning power" in role_only["next_question"]
    assert "may need temporary service or staged load" in role_only["hypothesis"]


def test_regulatory_dc_boilerplate_and_drilling_permit_do_not_out_rank_temporary_scope():
    generic_temporary = _item(
        name="Austin temporary service permit",
        location="Austin, TX",
        asset_type="unknown",
        activity="temporary-power",
        supported_action="Temporary service for construction power.",
        evidence=[
            {
                "id": uuid4(),
                "title": "Austin electrical permit",
                "abstract": "Temporary service for construction power.",
                "url": "https://example.test/temp",
                "content_hash": "3" * 64,
                "source_id": "austin-building-permits",
                "document_number": "2026-123456 EP",
            }
        ],
    )
    formation = _item(
        name="QTS ATL3",
        location="Augusta, GA",
        asset_type="data_center",
        activity="backup-power",
        lifecycle_state="project_formation",
        supported_action="QTS ATL3",
        evidence=[
            {
                "id": uuid4(),
                "title": "Draft stationary source permit",
                "abstract": (
                    "Operation of a data center with emergency generators. General "
                    "conditions discuss construction, startup and commissioning."
                ),
                "url": "https://example.test/ga-permit",
                "content_hash": "4" * 64,
                "source_id": "georgia-air-draft-title-v",
                "document_number": "30169",
            }
        ],
    )
    well_permit = _item(
        name="Texas W-1 well permit 0918935",
        location="Texas",
        asset_type="upstream_well",
        activity="well-permit",
        lifecycle_state="permitting",
        supported_action="W-1 permit: Recompletion.",
        evidence=[
            {
                "id": uuid4(),
                "title": "W-1 well permit",
                "abstract": "Drilling permit; compliance text references production operations.",
                "url": "https://example.test/w1",
                "content_hash": "5" * 64,
                "source_id": "texas-rrc-drilling-permits",
                "document_number": "0918935",
            }
        ],
    )
    ranked = cards([well_permit, formation, generic_temporary], {}, date(2026, 10, 3), 50)
    assert [card["id"] for card in ranked] == [
        str(generic_temporary["id"]),
        str(formation["id"]),
        str(well_permit["id"]),
    ]
    formed = build_card(formation, None, date(2026, 10, 3))
    assert formed["disposition"] == "WATCH"
    assert "mobilization" in formed["watch"]["event"]
    assert "actual construction stage" in formed["hypothesis"].casefold()
    assert build_card(well_permit, None, date(2026, 10, 3))["disposition"] == "WATCH"


def test_supported_production_transition_with_direct_contact_qualifies_discovery_question():
    item = _item(
        name="Cedar Draw gas facility",
        activity="production-startup",
        asset_type="upstream_well",
        lifecycle_state="producing",
        supported_action="Production started at Cedar Draw facility.",
        lifecycle_timeline=[
            {
                "event_type": "production_start",
                "state": "Producing",
                "date": "2026-10-01",
                "current": True,
            }
        ],
        evidence=[
            {
                "id": uuid4(),
                "title": "Current production transition",
                "abstract": "Production started at Cedar Draw facility.",
                "url": "https://example.test/production",
                "content_hash": "6" * 64,
                "event_date": "2026-10-01",
                "assessment_current": True,
            }
        ],
    )
    chain = {
        "candidates": [
            {
                "organization": "Cedar Draw Operating LLC",
                "organization_relationship": "DIRECT",
                "category": "operator",
                "stale": False,
                "public_contacts": [
                    {
                        "kind": "phone",
                        "value": "555-0103",
                        "source_url": "https://example.test/operator",
                    }
                ],
                "evidence": [],
            }
        ],
        "permit_summaries": [],
    }
    card = build_card(item, chain, date(2026, 10, 3))
    assert card["disposition"] == "ACTION NOW"
    assert "startup timing" in card["next_question"]
    assert "Gas fuel" in card["hypothesis"]


def test_surfaced_daily_counts_only_new_action_now_card():
    today = "2026-10-03"
    prior = {"input_hash": "old", "disposition": "RESEARCH", "surfaced_on": None}
    research = {"input_hash": "same", "disposition": "RESEARCH"}
    assert surfaced_on(prior, research, today) is None
    action = {"input_hash": "action", "disposition": "ACTION NOW"}
    assert surfaced_on(prior, action, today) == today
    assert (
        surfaced_on(
            {"input_hash": "action", "disposition": "ACTION NOW", "surfaced_on": today},
            action,
            today,
        )
        == today
    )


@pytest.mark.parametrize(
    "scope",
    [
        "No temporary power is required for this project; utility service serves all loads.",
        "Temporary power is not needed for this construction activity.",
        "This project does not require temporary power.",
    ],
)
def test_explicit_no_temporary_need_suppresses_contact_action(scope):
    item = _item(
        asset_type="manufacturing",
        name="Factory construction",
        supported_action="Factory construction",
        lifecycle_state="construction",
        evidence=[
            {
                "id": uuid4(),
                "title": "Factory construction permit",
                "abstract": scope,
                "url": "https://example.test/permit",
            }
        ],
    )
    chain = {
        "candidates": [
            {
                "organization": "Factory Inc",
                "category": "owner_operator",
                "organization_relationship": "DIRECT",
                "public_contacts": [{"kind": "phone", "value": "555-0100"}],
            }
        ]
    }
    card = build_card(item, chain, date(2026, 10, 5))
    assert card["disposition"] == "REJECT"
    assert card["tier"] == "Signal"


def test_negated_need_and_affirmative_scope_require_conflict_research():
    item = _item(
        asset_type="manufacturing",
        name="Factory construction",
        supported_action="Factory construction",
        lifecycle_state="construction",
        evidence=[
            {
                "id": uuid4(),
                "title": "Factory construction permit",
                "abstract": (
                    "Temporary power is not required. Construction power is required for phase two."
                ),
                "url": "https://example.test/permit",
            }
        ],
    )
    chain = {
        "candidates": [
            {
                "organization": "Factory Inc",
                "category": "owner_operator",
                "organization_relationship": "DIRECT",
                "public_contacts": [{"kind": "phone", "value": "555-0100"}],
            }
        ]
    }
    assert build_card(item, chain, date(2026, 10, 5))["disposition"] == "RESEARCH"
