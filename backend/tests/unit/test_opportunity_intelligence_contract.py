"""Commercial presentation never manufactures accepted facts or contact methods."""

from copy import deepcopy
from uuid import uuid4

import pytest

from gridlens.domain.opportunity_intelligence import (
    _source,
    assemble_card,
    contact_projection,
    normalize_gap,
)
from gridlens.ingestion.adapters.retained_document import SOURCES, stack_project_alias


def item():
    return {
        "id": str(uuid4()),
        "project_id": str(uuid4()),
        "name": "Example project",
        "tier": "Signal",
        "activity": "construction",
        "location": "Dallas, TX",
        "evidence": [
            {
                "id": str(uuid4()),
                "title": "Official permit",
                "url": "https://city.test/p",
                "abstract": "Example project construction",
                "assessment_current": True,
                "content_hash": "a" * 64,
                "source_id": "fort-worth-development-permits",
            }
        ],
    }


def test_completeness_never_promotes_or_turns_facility_load_into_power_gap():
    record = item()
    record["reported_power_facts"] = ["200 MW total campus capacity"]
    card = assemble_card(record, {}, {"disposition": "WATCH"}, [], research_enabled=False)
    assert card.qualification == "Signal"
    assert card.power_gap is None
    assert next(f for f in card.fields if f.key == "required_mw").value is None
    assert all(f.status != "Not publicly available" for f in card.research_gaps)
    assert all("disabled" in f.basis for f in card.research_gaps)


def test_title_only_current_demand_quote_is_cited_but_stale_or_unmatched_title_is_not():
    record = item()
    record.update(required_mw="5 MW", demand_quote="Construction requires 5 MW")
    record["evidence"][0]["title"] = "Permit: Construction requires 5 MW"
    card = assemble_card(record, {}, {}, [], research_enabled=False)
    field = next(field for field in card.fields if field.key == "required_mw")
    assert field.value == "5 MW"
    assert len(field.sources) == 1
    assert field.sources[0].passage == record["demand_quote"]
    assert field.sources[0].content_hash == record["evidence"][0]["content_hash"]

    stale = deepcopy(record)
    stale["evidence"][0]["assessment_current"] = False
    stale_card = assemble_card(stale, {}, {}, [], research_enabled=False)
    stale_field = next(field for field in stale_card.fields if field.key == "required_mw")
    assert stale_field.value is None
    assert stale_field.sources == []

    unmatched = deepcopy(record)
    unmatched["evidence"][0]["title"] = "Permit: electrical work"
    unmatched["evidence"][0]["abstract"] = "Construction at Example project."
    unmatched_card = assemble_card(unmatched, {}, {}, [], research_enabled=False)
    unmatched_field = next(field for field in unmatched_card.fields if field.key == "required_mw")
    assert unmatched_field.value is None
    assert unmatched_field.sources == []


def test_supply_fact_citation_requires_exact_canonical_fact_id_and_hash():
    record = item()
    record.update(
        tier="Lead",
        qualification_version="qualified-v1",
        required_mw="4–6 MW",
        supply_quote="Official service letter supplies 2–3 MW throughout the activity.",
        qualified_remaining_gap={
            "required_mw_min": "4",
            "required_mw_max": "6",
            "available_mw_min": "2",
            "available_mw_max": "3",
            "remaining_mw_min": "1",
            "remaining_mw_max": "4",
            "basis_quote": "Official service letter supplies 2–3 MW throughout the activity.",
            "suitable_supply_fact_id": "used-fact",
            "suitable_supply_fact_hash": "b" * 64,
        },
        operator_fact_refs=[
            {
                "fact_type": "suitable_supply",
                "fact_version_id": "unused-partial-supply",
                "content_hash": "c" * 64,
                "value": {"mw": "1", "window": "partial", "quality": "unknown"},
            },
            {
                "fact_type": "suitable_supply",
                "fact_version_id": "used-fact",
                "content_hash": "b" * 64,
                "value": {"mw": "2-3", "quality": "suitable"},
            },
        ],
    )
    record["evidence"][0]["abstract"] = record["supply_quote"]
    card = assemble_card(record, {}, {}, [], research_enabled=False)
    supply = next(field for field in card.fields if field.key == "supply")
    gap = next(field for field in card.fields if field.key == "gap")
    assert supply.value.replace("–", "-") == "2-3 MW"
    assert [source.reference for source in supply.sources] == [
        "evidence:" + record["evidence"][0]["id"],
        "operator-fact:used-fact",
    ]
    assert "operator-fact:used-fact" in [source.reference for source in gap.sources]
    assert "operator-fact:unused-partial-supply" not in [source.reference for source in gap.sources]

    for mismatch in (
        {"suitable_supply_fact_id": None, "suitable_supply_fact_hash": None},
        {"suitable_supply_fact_id": "different-fact", "suitable_supply_fact_hash": "c" * 64},
        {"suitable_supply_fact_id": "used-fact", "suitable_supply_fact_hash": "d" * 64},
    ):
        changed = deepcopy(record)
        changed["qualified_remaining_gap"].update(mismatch)
        changed_card = assemble_card(changed, {}, {}, [], research_enabled=False)
        changed_supply = next(field for field in changed_card.fields if field.key == "supply")
        changed_gap = next(field for field in changed_card.fields if field.key == "gap")
        assert all(
            not source.reference.startswith("operator-fact:") for source in changed_supply.sources
        )
        assert all(
            not source.reference.startswith("operator-fact:") for source in changed_gap.sources
        )


def test_failed_research_is_not_proof_information_is_not_public():
    card = assemble_card(
        item(), {}, {}, [{"category": "load", "status": "FAILED"}], research_enabled=True
    )
    field = next(f for f in card.fields if f.key == "required_mw")
    assert field.status == "Research in progress"
    assert "failed" in field.basis
    assert field.value is None


def test_owner_developer_is_headline_while_contractor_remains_in_buying_chain():
    owner = party()
    owner.update(
        id=str(uuid4()),
        company_identity_id=str(uuid4()),
        organization="Orion Development",
        category="owner_developer",
    )
    contractor = party()
    contractor.update(
        id=str(uuid4()),
        company_identity_id=str(uuid4()),
        organization="Example EPC",
        category="epc",
    )
    card = assemble_card(
        item(),
        {"candidates": [contractor, owner]},
        {"disposition": "RESEARCH"},
        [],
        research_enabled=False,
    )
    assert next(field for field in card.fields if field.key == "customer").value == (
        "Orion Development"
    )
    assert [contact.company for contact in card.contacts] == [
        "Orion Development",
        "Example EPC",
    ]


@pytest.mark.parametrize("scalar", [False, True])
def test_official_and_operator_gap_shapes_keep_same_arithmetic_and_provenance(scalar):
    record = item()
    record.update(
        tier="Lead",
        qualification_version="qualified-v1",
        start_window="2027-01-01",
        duration="30 days",
    )
    gap = (
        {
            "suitable_supply_fact_id": "operator-fact",
            "required_mw": "5",
            "available_mw": "2",
            "remaining_mw": "3",
        }
        if scalar
        else {
            "required_mw_min": "4",
            "required_mw_max": "5",
            "available_mw_min": "1",
            "available_mw_max": "2",
            "remaining_mw_min": "2",
            "remaining_mw_max": "4",
            "basis_quote": "Suitable supply covers the entire activity interval.",
        }
    )
    record["qualified_remaining_gap"] = gap
    normalized = normalize_gap(record)
    assert normalized and normalized["duration"] == "30 days"
    assert normalized["remaining_mw_min"] == ("3" if scalar else "2")
    if scalar:
        assert normalized["suitable_supply_fact_id"] == "operator-fact"
    changed = deepcopy(record)
    changed["qualified_remaining_gap"]["remaining_mw_min"] = "99"
    assert normalize_gap(changed) is None
    for tier in ("Signal", "Prospect"):
        assert normalize_gap({**record, "tier": tier}) is None
    assert normalize_gap({**record, "conflict_state": "CONFLICT"}) is None


def party():
    return {
        "id": str(uuid4()),
        "organization": "Example EPC",
        "person_name": "Alex Example",
        "title": "Project manager",
        "category": "epc",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "DIRECT",
        "person_project_relationship": "DIRECT",
        "evidence": [
            {
                "id": str(uuid4()),
                "current_support": True,
                "supports": "public_contact",
                "url": "https://epc.test/contact",
                "quote": "Business: alex@epc.test",
            }
        ],
        "public_contacts": [
            {
                "kind": "email",
                "value": "alex@epc.test",
                "source_url": "https://epc.test/contact",
                "quote": "Business: alex@epc.test",
            }
        ],
    }


def test_contact_actions_require_exact_current_contact_quote_and_do_not_assert_authority():
    candidate = party()
    contacts = contact_projection({"candidates": [candidate]})
    assert contacts[0].methods[0]["href"] == "mailto:alex@epc.test"
    assert contacts[0].purchasing_authority.startswith("Requires confirmation")
    candidate["public_contacts"][0]["value"] = "invented@epc.test"
    assert contact_projection({"candidates": [candidate]})[0].methods == []
    candidate["evidence"][0]["current_support"] = False
    assert contact_projection({"candidates": [candidate]}) == []


def test_contractor_is_never_customer_and_project_identity_remains_distinct():
    a, b = item(), item()
    chain = {"candidates": [party()]}
    cards = [assemble_card(i, chain, {}, [], research_enabled=True) for i in (a, b)]
    assert cards[0].project_id != cards[1].project_id
    for card in cards:
        assert next(f for f in card.fields if f.key == "customer").value is None
        assert card.contacts[0].company == "Example EPC"


def test_conflicting_dates_never_display_verified_even_with_canonical_value():
    record = item()
    record.update(
        start_window="2027-01-01",
        conflict_state="CONFLICT",
        research_state={"activity_start": {"status": "CONFLICT", "claims": []}},
    )
    card = assemble_card(record, {}, {}, [], research_enabled=True)
    field = next(f for f in card.fields if f.key == "start")
    assert field.value is None and field.status == "Conflicting evidence"


def test_supported_public_load_uses_exact_claim_without_changing_signal_qualification():
    record = item()
    evidence = record["evidence"][0]
    evidence["abstract"] = "Example project construction requires 2 MW."
    record["research_state"] = {
        "activity_load_mw": {
            "status": "SUPPORTED",
            "value": "2",
            "claims": [
                {
                    "evidence_id": evidence["id"],
                    "evidence_hash": evidence["content_hash"],
                    "quote": evidence["abstract"],
                }
            ],
        }
    }
    card = assemble_card(record, {}, {}, [], research_enabled=True)
    field = next(f for f in card.fields if f.key == "required_mw")
    assert field.value == "2 MW (source-reported)"
    assert field.status == "Source-reported"
    assert field.sources[0].verification_status == "Current source-reported claim"
    assert field.sources[0].passage == evidence["abstract"]
    assert card.qualification == "Signal" and card.power_gap is None
    record["research_state"]["activity_load_mw"]["claims"][0]["evidence_hash"] = "wrong"
    card = assemble_card(record, {}, {}, [], research_enabled=True)
    assert next(f for f in card.fields if f.key == "required_mw").value is None


def test_reported_facility_scale_and_source_native_identity_remain_separate():
    record = item()
    evidence = record["evidence"][0]
    evidence["abstract"] = (
        "Project: Edged Energy Outpost Building 2\n"
        "Permit: PB26-11109\n"
        "Work description: 488,628 SF 196MW data center\n"
        "Orion Data Center facility electrical demand is 12 MW.\n"
        "Orion Data Center construction temporary power fuel is available.\n"
        "Orion Data Center construction temporary power voltage requirement is 480 V, 3 phase.\n"
        "Orion Data Center construction load profile is continuous."
    )
    record["name"] = "Permit PB26-11109"
    record["research_state"] = {
        "facility_scale_mw": {
            "status": "SUPPORTED",
            "value": "196",
            "claims": [
                {
                    "evidence_id": evidence["id"],
                    "evidence_hash": evidence["content_hash"],
                    "quote": "Work description: 488,628 SF 196MW data center",
                }
            ],
        }
    }
    for field, value, quote in (
        ("facility_demand_mw", "12", "Orion Data Center facility electrical demand is 12 MW."),
        (
            "fuel_availability",
            "available",
            "Orion Data Center construction temporary power fuel is available.",
        ),
        (
            "voltage",
            "480 V, 3 phase",
            "Orion Data Center construction temporary power voltage requirement is 480 V, 3 phase.",
        ),
        (
            "load_profile",
            "continuous",
            "Orion Data Center construction load profile is continuous.",
        ),
    ):
        record["research_state"][field] = {
            "status": "SUPPORTED",
            "value": value,
            "claims": [
                {
                    "evidence_id": evidence["id"],
                    "evidence_hash": evidence["content_hash"],
                    "quote": quote,
                }
            ],
        }
    card = assemble_card(record, {}, {"disposition": "WATCH"}, [], research_enabled=True)
    fields = {field.key: field for field in card.fields}
    assert fields["project"].value == "Edged Energy Outpost Building 2"
    assert fields["source_identifier"].value == "PB26-11109"
    assert fields["facility_scale"].value == "196 MW (reported facility scale)"
    assert "not establish total planned electrical demand" in fields["facility_scale"].basis
    assert fields["facility_demand"].value == "12 MW (source-reported facility demand)"
    assert fields["fuel"].value == "available"
    assert fields["voltage"].value == "480 V, 3 phase"
    assert fields["load_profile"].value == "continuous"
    assert fields["required_mw"].value is None
    assert card.power_gap is None


def test_generic_permit_name_is_not_presented_as_project_identity():
    record = item()
    record["name"] = "Boston permit ETS1870328"
    record["evidence"][0]["abstract"] = (
        "Permit number: ETS1870328\nComments: Replace existing ATS switch with new one."
    )
    card = assemble_card(record, {}, {"disposition": "WATCH"}, [], research_enabled=True)
    fields = {field.key: field for field in card.fields}
    assert fields["project"].value is None
    assert fields["source_identifier"].value == "ETS1870328"


@pytest.mark.parametrize("proof_after_excerpt", [False, True])
def test_f17_compound_project_name_requires_exact_current_source_alias_and_site_quotes(
    proof_after_excerpt,
):
    policy = SOURCES["f17-stack-cec-filing"]
    record = item()
    evidence = record["evidence"][0]
    evidence.update(
        source_id="f17-stack-cec-filing",
        url=policy["url"],
        title="SVY02A / Memorex Junction data center — retained filing",
        content_hash=policy["sha256"],
        retained_evidence_id=evidence["id"],
        assessment_current=True,
        abstract=(
            "The figures represented for SVY02A Memorex will be used in the Memorex Junction "
            "Operational Study. STACK became owner of the data center project, a.k.a. "
            "�Memorex Junction,� and heads the Development Team. The 1200 Memorex\nDrive "
            "project is in the City of Santa Clara."
        ),
    )

    if proof_after_excerpt:
        evidence["abstract"] = (
            "Background outside the compact preview. " * 40 + evidence["abstract"]
        )

    def project_field(value):
        card = assemble_card(value, {}, {"disposition": "WATCH"}, [], research_enabled=False)
        return next(field for field in card.fields if field.key == "project")

    project = project_field(record)
    assert project.value == "SVY02A / Memorex Junction data center"
    assert len(project.sources) == 3
    assert all(source.passage in evidence["abstract"] for source in project.sources)
    assert any("SVY02A Memorex" in source.passage for source in project.sources)
    assert any("a.k.a." in source.passage for source in project.sources)

    normalized = _source(evidence)
    assert stack_project_alias(record, [normalized]).status == "verified"
    assert "evidence_text" not in normalized.model_dump()
    if proof_after_excerpt:
        assert "SVY02A Memorex" not in normalized.passage
    wrong_normalized_id = normalized.model_copy(
        update={"retained_evidence_id": "mismatched-canonical-row"}
    )
    assert stack_project_alias(record, [wrong_normalized_id]).status == "handled_without_proof"
    wrong_reference = normalized.model_copy(update={"reference": "evidence:mismatched-row"})
    assert stack_project_alias(record, [wrong_reference]).status == "handled_without_proof"

    wrong_hash = deepcopy(record)
    wrong_hash["evidence"][0]["content_hash"] = "wrong-version"
    assert project_field(wrong_hash).value is None
    title_only = deepcopy(record)
    title_only["evidence"][0]["abstract"] = "Generic CEC filing without project aliases."
    assert project_field(title_only).value is None
    wrong_source = deepcopy(record)
    wrong_source["evidence"][0]["source_id"] = "other-retained-source"
    assert project_field(wrong_source).value is None
    for field, value in (
        ("url", "https://example.test/cec"),
        ("assessment_current", False),
        ("abstract", "SVY02A Memorex Operational Study; owner alias at another site."),
    ):
        invalid = deepcopy(record)
        invalid["evidence"][0][field] = value
        assert project_field(invalid).value is None
    no_retained_row_id = deepcopy(record)
    no_retained_row_id["evidence"][0]["retained_evidence_id"] = None
    assert project_field(no_retained_row_id).value == "SVY02A / Memorex Junction data center"


def test_crusoe_project_name_remains_directly_source_native():
    policy = SOURCES["f17-crusoe-impact"]
    record = item()
    record["supported_subject"] = "Abilene Stargate campus"
    record["evidence"][0].update(
        source_id="f17-crusoe-impact",
        url=policy["url"],
        content_hash=policy["sha256"],
        retained_evidence_id=str(uuid4()),
        assessment_current=True,
        abstract="The Abilene Stargate campus is identified in the report.",
    )
    card = assemble_card(record, {}, {"disposition": "WATCH"}, [], research_enabled=False)
    project = next(field for field in card.fields if field.key == "project")
    assert project.value == "Abilene Stargate campus"
    assert project.sources[0].passage == record["evidence"][0]["abstract"]


def test_f17_commercial_reason_and_action_reach_visible_intelligence_projection():
    record = item()
    record["evidence"] = []
    for source_id, abstract in (
        (
            "f17-stack-city-claim",
            "At 1200 Memorex Drive in Santa Clara, STACK reports an 18 MVA cap through "
            "2028, against earlier 28 MVA 2026 / 31 MVA 2027 schedule.",
        ),
        (
            "f17-stack-cec-filing",
            "At 1200 Memorex Drive in Santa Clara, the draft Table E1 available capacity "
            "schedule (MVA) lists 28 and 31.",
        ),
    ):
        policy = SOURCES[source_id]
        record["evidence"].append(
            {
                "id": str(uuid4()),
                "retained_evidence_id": str(uuid4()),
                "source_id": source_id,
                "title": "Retained source excerpt",
                "url": policy["url"],
                "abstract": abstract,
                "content_hash": policy["sha256"],
                "assessment_current": True,
            }
        )
    reason = (
        "STACK's city claim reports an earlier 28 MVA (2026) / 31 MVA (2027) schedule; "
        "the separate CEC schedule is draft. Current service and temporary-power need UNKNOWN."
    )
    action = "Verify the current utility delivery schedule and temporary-power scope."
    card = assemble_card(
        record,
        {},
        {"disposition": "WATCH", "reason": reason, "next_action": action},
        [],
        research_enabled=False,
    )
    assessment = next(field for field in card.fields if field.key == "assessment")
    assert assessment.value == reason
    assert {source.source_id for source in assessment.sources} == {
        "f17-stack-city-claim",
        "f17-stack-cec-filing",
    }
    assert card.next_action == action
    assert card.qualification == record["tier"]
    assert card.disposition == "WATCH"
    assert card.power_gap is None


@pytest.mark.parametrize(
    ("source_id", "abstract", "project", "identifier"),
    [
        (
            "texas-rrc-drilling-permits",
            "row: 0761171\nlease: HAUG-KIESCHNICK AC UNIT 33\nwell: 1H\n",
            "HAUG-KIESCHNICK AC UNIT 33, well 1H",
            "0761171",
        ),
        (
            "austin-building-permits",
            "row: 2026-068264 EP\ndescription: Temporary service for (6) fans and construction "
            "power for TXDOT project # 14-0914-04-362R.\n",
            "TXDOT project # 14-0914-04-362R",
            "2026-068264 EP",
        ),
    ],
)
def test_source_specific_rrc_and_austin_names_keep_raw_record_identifier(
    source_id, abstract, project, identifier
):
    record = item()
    record["name"] = "Generic permit record"
    record["evidence"][0].update(source_id=source_id, abstract=abstract)
    card = assemble_card(record, {}, {"disposition": "WATCH"}, [], research_enabled=True)
    fields = {field.key: field for field in card.fields}
    assert fields["project"].value == project
    assert fields["source_identifier"].value == identifier
    project_quote = fields["project"].sources[0].passage
    assert (
        "HAUG-KIESCHNICK AC UNIT 33" in project_quote and "well: 1H" in project_quote
    ) or project in project_quote
    assert identifier in fields["source_identifier"].sources[0].passage


def test_late_austin_project_reference_keeps_default_citation_compact():
    record = item()
    record["name"] = "Generic permit record"
    record["evidence"][0].update(
        source_id="austin-building-permits",
        abstract=(
            "row: 2026-068264 EP\n"
            + "Retained background. " * 80
            + "\ndescription: "
            + "Supporting permit detail. " * 100
            + "Construction power for TXDOT project # 14-0914-04-362R. "
            + "Supporting permit detail. " * 200
            + "RAW-TAIL"
        ),
    )
    card = assemble_card(record, {}, {"disposition": "WATCH"}, [], research_enabled=False)
    project = next(field for field in card.fields if field.key == "project")
    assert project.value == "TXDOT project # 14-0914-04-362R"
    assert project.value in project.sources[0].passage
    assert len(project.sources[0].passage) <= 641
    assert "RAW-TAIL" not in card.model_dump_json()


@pytest.mark.parametrize(
    ("source_id", "abstract", "expected_identifier"),
    [
        (
            "texas-rrc-drilling-permits",
            "row: 0761171\nlease: HAUG-KIESCHNICK AC UNIT 33\n",
            "0761171",
        ),
        (
            "austin-building-permits",
            "row: **bad**\ndescription: TXDOT project # ???\n",
            None,
        ),
        (
            "publisher-rss",
            "row: 0761171\nlease: HAUG-KIESCHNICK AC UNIT 33\nwell: 1H\n",
            None,
        ),
    ],
)
def test_source_native_project_names_and_row_ids_fail_closed(
    source_id, abstract, expected_identifier
):
    record = item()
    record["name"] = "Generic permit record"
    record["supported_subject"] = None
    record["evidence"][0].update(source_id=source_id, abstract=abstract)
    fields = {
        field.key: field
        for field in assemble_card(
            record, {}, {"disposition": "WATCH"}, [], research_enabled=True
        ).fields
    }
    assert fields["project"].value is None
    assert fields["source_identifier"].value == expected_identifier


def test_source_native_project_name_and_row_id_require_current_evidence():
    record = item()
    record["name"] = "Generic permit record"
    record["supported_subject"] = None
    record["evidence"][0].update(
        source_id="austin-building-permits",
        abstract=(
            "row: 2026-068264 EP\ndescription: Temporary service and construction power "
            "for TXDOT project # 14-0914-04-362R.\n"
        ),
        assessment_current=False,
    )
    fields = {
        field.key: field
        for field in assemble_card(
            record, {}, {"disposition": "WATCH"}, [], research_enabled=True
        ).fields
    }
    assert fields["project"].value is None
    assert fields["source_identifier"].value is None


@pytest.mark.parametrize(
    ("title", "abstract", "expected"),
    [
        (
            "QTS ATL3",
            "Facility: QTS ATL3\nFacility Name: QTS ATL3 Campus\n"
            "QTS ATL3 Campus is proposed greenfield to be located at 2883 Gordon Highway, "
            "Augusta, Richmond County.",
            "QTS ATL3 Campus",
        ),
        (
            "TADG \ufffd ATL02 / Ellenwood",
            "Official narrative excerpt: Page 1: NARRATIVE Facility Name: TADG – ATL02 "
            "AIRS No.: 063-00154 Location: Ellenwood, GA (Clayton County)\n",
            "TADG – ATL02",
        ),
    ],
)
def test_explicit_narrative_facility_name_precedes_title_or_summary(title, abstract, expected):
    record = item()
    record["name"] = title
    if title == "QTS ATL3":
        record["supported_subject"] = "QTS ATL3"
        record["evidence"][0]["source_id"] = "georgia-air-draft-title-v"
    record["location"] = "Augusta, Georgia"
    record["evidence"][0].update(title=title, abstract=abstract)
    fields = {
        field.key: field
        for field in assemble_card(record, {}, {}, [], research_enabled=False).fields
    }
    assert fields["project"].value == expected
    if title == "QTS ATL3":
        assert fields["location"].value == "2883 Gordon Highway, Augusta, Richmond County"
        assert "2883 Gordon Highway" in fields["location"].sources[0].passage


def test_unrelated_operator_fact_cannot_ground_demand_and_missing_contacts_are_gaps():
    record = item()
    record["required_mw"] = "9 MW"
    record["operator_fact_refs"] = [
        {
            "fact_version_id": str(uuid4()),
            "content_hash": "a" * 64,
            "fact_type": "buyer",
            "value": {"organization": "Buyer"},
        }
    ]
    card = assemble_card(record, {}, {}, [], research_enabled=True)
    assert next(f for f in card.fields if f.key == "required_mw").value is None
    assert {"contact_path", "project_contact"}.issubset({f.key for f in card.research_gaps})


def test_public_chain_document_has_namespaced_reference_without_fake_evidence_fk():
    contact = contact_projection({"candidates": [party()]})[0]
    assert contact.sources[0].reference.startswith("buying-chain:")
    assert contact.sources[0].retained_evidence_id is None


def test_expanded_planning_is_opt_in_and_known_owner_prevents_repeated_identity_research():
    from gridlens.domain.pursuit_research import plan_questions

    card = {
        "disposition": "ACTION NOW",
        "owner_organizations": ["Actual Owner"],
        "organization": "EPC First",
        "organization_role": "epc",
        "facts": [],
        "stage": {"stage": "construction", "evidence_id": "source"},
    }
    assert plan_questions(card) == []
    planned = plan_questions(card, enrich=True)
    assert len(planned) <= 2
    assert all(q["category"] not in {"identity", "suitability"} for q in planned)
    card["owner_organizations"] = []
    assert plan_questions(card, enrich=True)[0]["category"] == "identity"


def test_display_enrichment_preserves_legacy_research_fingerprint():
    from gridlens.domain.commercial_triage import _semantic_card

    legacy = {
        "id": "need",
        "organization": "Owner",
        "operator_fact_refs": [
            {
                "need_id": "need",
                "fact_version_id": "fact",
                "content_hash": "hash",
                "authority": "User-confirmed",
            }
        ],
    }
    enriched = deepcopy(legacy)
    enriched.update(owner_organizations=["Owner"], intelligence_card={"policy_version": "v1"})
    enriched["operator_fact_refs"][0].update(fact_type="demand", value={"mw": "5"})
    assert _semantic_card(enriched) == legacy


def test_rental_intermediary_is_not_recommended_as_customer_contact():
    candidate = party()
    candidate["category"] = "rental_intermediary"
    assert contact_projection({"candidates": [candidate]}) == []
