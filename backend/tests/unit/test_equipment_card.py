"""Calculated equipment results stay source-bound on the opportunity card."""

from gridlens.domain.opportunity_intelligence import assemble_card


def test_calculated_demand_appears_as_separate_evidence_bound_card_projection():
    evidence_id = "evidence-123"
    evidence_hash = "a" * 64
    abstract = (
        "Facility: Prairie Example LLC\n"
        "Equipment ID: C-101 | Type: compressor | Drive: electric | "
        "Rating: 1000 hp mechanical output | Count: 2 | Operating: 1 | "
        "State: proposed | Role: duty | Efficiency: 0.90"
    )
    equipment_demand = {
        "status": "SUPPORTED",
        "classification": "CALCULATED",
        "demand": {
            "connected_kw": "1657.110826666666666666666667",
            "coincident_kw": "828.5554133333333333333333333",
        },
        "evidence": [
            {
                "evidence_id": evidence_id,
                "evidence_hash": evidence_hash,
                "quote": (
                    "Equipment ID: C-101 | Type: compressor | Drive: electric | "
                    "Rating: 1000 hp mechanical output | Count: 2 | Operating: 1 | "
                    "State: proposed | Role: duty | Efficiency: 0.90"
                ),
            }
        ],
        "residual_gap_kw": None,
        "unresolved_questions": ["Utility supply is unknown."],
        "next_action": "Review the cited equipment schedule.",
    }
    item = {
        "id": "need-123",
        "project_id": "project-123",
        "tier": "Signal",
        "location": "Tulsa, OK",
        "activity": "facility-expansion",
        "lifecycle_state": None,
        "evidence": [
            {
                "id": evidence_id,
                "source_id": "synthetic-equipment",
                "title": "Equipment schedule",
                "abstract": abstract,
                "url": "https://example.test/schedule",
                "content_hash": evidence_hash,
                "published_at": None,
                "observed_at": "2026-10-30T12:00:00Z",
                "extraction_location": "Synthetic fixture",
                "assessment_current": True,
            }
        ],
        "supported_subject": "Prairie Example LLC",
        "research_state": {},
        "operator_fact_refs": [],
        "power_field_provenance": {},
        "conflict_state": None,
        "equipment_demand": equipment_demand,
    }

    card = assemble_card(
        item,
        {"candidates": []},
        {
            "disposition": "RESEARCH",
            "reason": "Early evidence merits investigation.",
            "next_action": "Review the source.",
        },
        [],
        research_enabled=False,
    )
    projected = card.model_dump(mode="json")
    field = next(
        value for value in projected["fields"] if value["key"] == "calculatedEquipmentDemand"
    )
    assert field["status"] == "Calculated"
    assert field["value"].startswith("828.5554133")
    assert field["sources"][0]["reference"] == "equipment-evidence:" + evidence_id
    assert projected["equipment_demand"] == equipment_demand
    assert projected["qualification"] == "Signal"
    assert "not a supply gap" in field["basis"]


def test_partial_equipment_projection_does_not_fill_unknown_load():
    item = {
        "id": "need-123",
        "project_id": "project-123",
        "tier": "Signal",
        "location": "Tulsa, OK",
        "activity": "facility-expansion",
        "evidence": [],
        "research_state": {},
        "operator_fact_refs": [],
        "power_field_provenance": {},
        "equipment_demand": {
            "status": "PARTIAL",
            "category": "UNKNOWN",
            "demand": {"coincident_kw": None},
            "evidence": [],
            "residual_gap_kw": None,
        },
    }
    card = assemble_card(
        item,
        {"candidates": []},
        {"disposition": "RESEARCH", "next_action": "Review evidence."},
        [],
        research_enabled=False,
    )
    field = next(value for value in card.fields if value.key == "calculatedEquipmentDemand")
    assert field.value is None
    assert field.status == "Research in progress"
    assert card.power_gap is None
    assert card.qualification == "Signal"
