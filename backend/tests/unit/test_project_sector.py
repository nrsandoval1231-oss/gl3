from gridlens.intelligence.opportunity_browse import add_browse_evidence
from gridlens.intelligence.project_sector import result_metadata


def test_retained_rrc_permit_produces_well_identity_and_permit_event_only():
    result = result_metadata(
        {
            "name": "Pioneer permit 0918069",
            "_browse_rrc_records": [
                {
                    "source_id": "texas-rrc-drilling-permits",
                    "evidence_id": "ev-1",
                    "operator": "PIONEER NATURAL RESOURCES USA, INC.",
                    "operator_number": "665748",
                    "lease": "GLASSCOCK-DICKENSON 44C",
                    "well": "3H",
                    "date": "2026-09-24",
                    "status": "Approved",
                }
            ],
        }
    )
    assert result["sector"] == "oil_gas"
    assert result["operator"] == "PIONEER NATURAL RESOURCES USA, INC."
    assert result["oil_gas"] == {
        "operator": "PIONEER NATURAL RESOURCES USA, INC.",
        "operator_number": "665748",
        "lease": "GLASSCOCK-DICKENSON 44C",
        "well_number": "3H",
        "status": "Approved",
        "permit_issue_date": "2026-09-24",
    }
    assert result["event"] == {
        "kind": "permit_issued",
        "label": "Permit issued",
        "date": "2026-09-24",
        "source": "texas-rrc-drilling-permits",
        "evidence_refs": ["ev-1"],
    }
    assert "spud_date" not in result["oil_gas"]
    assert "demand and timing are not established" in result["power_summary"]


def test_conflicting_rrc_well_identity_is_not_collapsed():
    rows = [
        {"operator": "Operator A", "lease": "Lease 1", "well": "1H", "date": "2026-09-24"},
        {"operator": "Operator A", "lease": "Lease 2", "well": "2H", "date": "2026-09-24"},
    ]
    result = result_metadata({"_browse_rrc_records": rows})
    assert result["sector"] == "oil_gas"
    assert result["oil_gas"] == {}
    assert result["event"] is None


def test_data_center_owner_and_explicit_phase_are_retained_without_power_claim():
    result = result_metadata(
        {
            "name": "EG AI Rice Data Center Campus",
            "asset_type": "data_center",
            "owner_name": "EG AI CORP",
            "phase": "Project Registered",
            "planned_start_date": "2026-11-06",
            "energization_date": None,
        }
    )
    assert result["sector"] == "data_centers"
    assert result["owner"] == "EG AI CORP"
    assert result["data_center"]["phase"] == "Project Registered"
    assert "planned_start_date" not in result["data_center"]
    assert result["event"] is None
    assert "gap are not established" in result["power_summary"]


def test_current_tdlr_fields_produce_owner_phase_and_planned_event_with_source_label():
    item = {"name": "EG AI Rice Data Center Campus", "asset_type": "data_center"}
    add_browse_evidence(
        item,
        {
            "id": "tdlr-ev-1",
            "source_id": "texas-tdlr-tabs-data-centers",
            "document_number": "TABS2027002808",
            "assessment_current": True,
            "abstract": "\n".join(
                [
                    "Project: EG AI Rice Data Center (Facility not named)",
                    "Registered: 2026-10-05",
                    "Developer-reported start: 2026-11-06; completion: 2028-04-30",
                    "Owner: EG AI CORP",
                    "TABS status: Project Registered",
                ]
            ),
        },
    )
    result = result_metadata({**item, "_browse_tdlr_records": item["_browse_tdlr_records"]})
    assert result["sector"] == "data_centers"
    assert result["owner"] == "EG AI CORP"
    assert result["name"] == "EG AI Rice Data Center"
    assert result["data_center"] == {
        "owner_developer": "EG AI CORP",
        "campus": "EG AI Rice Data Center",
        "phase": "Project Registered",
        "registration_date": "2026-10-05",
        "developer_reported_start_date": "2026-11-06",
        "developer_reported_completion_date": "2028-04-30",
    }
    assert result["event"]["kind"] == "developer_reported_planned_start"
    assert result["event"]["label"] == "Developer-reported planned start"
    assert result["event"]["evidence_refs"] == ["tdlr-ev-1"]
    assert result["data_center"].get("energization_date") is None


def test_supported_data_center_power_summary_survives_generic_fallback():
    result = result_metadata(
        {
            "name": "Data center campus",
            "asset_type": "data_center",
            "required_mw": 42,
            "intelligence_card": {
                "power_summary": "40 MW committed utility supply; temporary demand remains unknown."
            },
        }
    )
    assert result["power_summary"] == (
        "40 MW committed utility supply; temporary demand remains unknown."
    )


def test_stale_tdlr_evidence_does_not_create_project_metadata():
    item = {"name": "EG AI Rice Data Center Campus", "asset_type": "data_center"}
    add_browse_evidence(
        item,
        {
            "source_id": "texas-tdlr-tabs-data-centers",
            "assessment_current": False,
            "abstract": "Owner: Wrong Owner\nTABS status: Project Registered",
        },
    )
    result = result_metadata({**item, "_browse_tdlr_records": item.get("_browse_tdlr_records", [])})
    assert result["owner"] is None
    assert result["event"] is None


def test_general_industrial_and_unrelated_rows_remain_other():
    assert result_metadata({"name": "Industrial plant upgrade"})["sector"] == "other"
    assert result_metadata({"name": "Utility substation"})["sector"] == "other"
    from gridlens.domain.lifecycle import classify_event

    for title in (
        "Municipal water pipeline construction permit",
        "Utility natural gas pipeline expansion",
        "Industrial air separation cryogenic plant",
    ):
        classified = classify_event(title)
        assert classified is not None
        assert (
            result_metadata({"name": title, "asset_type": classified.asset_type.value})["sector"]
            == "other"
        )
    attributed = result_metadata(
        {
            "name": "Field gathering compressor station",
            "asset_type": "compressor_station",
            "_browse_oil_gas_relationship": [
                {
                    "verified": True,
                    "source_id": "accepted-field-report",
                    "evidence_id": "field-ev",
                    "matched_context": ["natural gas gathering"],
                }
            ],
        }
    )
    assert attributed["sector"] == "oil_gas"
    assert (
        result_metadata(
            {
                "name": "",
                "_browse_rrc_records": [
                    {"operator": "Operator", "lease": "L", "well": "1H", "date": "yesterday"}
                ],
            }
        )["oil_gas"].get("permit_issue_date")
        is None
    )


def test_oil_gas_requires_attributed_asset_class_and_data_center_wins_mixed_name():
    assert result_metadata({"name": "Natural gas utility pipeline project"})["sector"] == "other"
    mixed = result_metadata(
        {
            "name": "Gas powered data center campus",
            "asset_type": "data_center",
            "owner_name": "EG AI CORP",
        }
    )
    assert mixed["sector"] == "data_centers"


def test_current_explicit_gathering_evidence_supplies_the_industry_relationship():
    from gridlens.domain.lifecycle import classify_event

    item = {"name": "Natural gas gathering pipeline extension"}
    add_browse_evidence(
        item,
        {
            "id": "gathering-ev",
            "source_id": "county-industrial-permits",
            "document_number": "PERMIT-1",
            "assessment_current": True,
            "title": "Natural gas gathering pipeline extension",
            "abstract": "Construct a natural gas gathering system serving upstream gas wells.",
        },
    )
    classification = classify_event(item["name"])
    assert classification is not None
    result = result_metadata(
        {
            "name": item["name"],
            "asset_type": classification.asset_type.value,
            "_browse_oil_gas_relationship": item["_browse_oil_gas_relationship"],
        }
    )
    assert result["sector"] == "oil_gas"
    assert result["oil_gas"]["relationship_evidence_refs"] == ["gathering-ev"]


def test_utility_and_air_separation_context_do_not_validate_oil_gas_relationship():
    item = {"name": "Natural gas gathering pipeline extension"}
    add_browse_evidence(
        item,
        {
            "id": "utility-ev",
            "source_id": "utility-projects",
            "assessment_current": True,
            "title": "Municipal water utility natural gas gathering pipeline",
            "abstract": "Industrial air separation supplies public utility natural gas.",
        },
    )
    assert not item.get("_browse_oil_gas_relationship")


def test_verified_rrc_facts_add_api_and_dates_without_lifting_old_recompletion_over_permit():
    official = {
        "identity_validated": True,
        "source": "texas-rrc-completion-packet",
        "native_content_hash": "a" * 64,
        "source_url": "https://webapps.rrc.texas.gov/CMPL/packet",
        "asset_identity": {
            "kind": "us_well_api",
            "value": "4216538299",
            "evidence_refs": ["ev-w2"],
        },
        "identity": {
            "operator": "OXY USA WTP LP",
            "operator_number": "630555",
            "lease": "WEST SEMINOLE SA UNIT",
            "well": "604R",
            "county": "GAINES",
            "county_code": "329",
        },
        "events": [
            {
                "kind": "historical_recompletion",
                "label": "Recompletion reported (historical)",
                "date": "2016-06-02",
                "source": "texas-rrc-completion-packet",
                "evidence_refs": ["ev-w2"],
            }
        ],
        "evidence_refs": ["ev-w2"],
    }
    result = result_metadata(
        {
            "name": "RRC permit 0918877",
            "browse_title": "OXY USA WTP LP · WEST SEMINOLE SA UNIT · Well 604R",
            "source_id": "texas-rrc-drilling-permits",
            "_browse_rrc_records": [
                {
                    "source_id": "texas-rrc-drilling-permits",
                    "document_number": "0918877",
                    "evidence_id": "ev-w1",
                    "operator": "OXY USA WTP LP",
                    "operator_number": "630555",
                    "lease": "WEST SEMINOLE SA UNIT",
                    "well": "604R",
                    "county_code": "329",
                    "date": "2026-09-24",
                    "status": "Approved",
                }
            ],
            "_browse_rrc_official": official,
        }
    )
    assert result["asset_identity"] == {
        "kind": "us_well_api",
        "value": "4216538299",
        "source": "Texas Railroad Commission official well record",
        "evidence_refs": ["ev-w2"],
        "identity_validated": True,
    }
    assert result["oil_gas"]["historical_recompletion_date"] == "2016-06-02"
    assert result["oil_gas"]["permit_issue_date"] == "2026-09-24"
    assert result["event"]["label"] == "Permit issued"


def test_verified_rrc_spud_event_after_permit_becomes_current_lifecycle_event():
    result = result_metadata(
        {
            "name": "permit 0918069",
            "source_id": "texas-rrc-drilling-permits",
            "_browse_rrc_records": [
                {
                    "source_id": "texas-rrc-drilling-permits",
                    "document_number": "0918069",
                    "operator": "PIONEER NATURAL RES. USA, INC.",
                    "operator_number": "665748",
                    "lease": "GLASSCOCK-DICKENSON 44C",
                    "well": "3H",
                    "county_code": "317",
                    "date": "2026-09-24",
                    "status": "Approved",
                }
            ],
            "_browse_rrc_official": {
                "identity_validated": True,
                "source": "texas-rrc-w1-detail",
                "native_content_hash": "b" * 64,
                "source_url": "https://webapps2.rrc.texas.gov/EWA/detail",
                "asset_identity": {
                    "kind": "us_well_api",
                    "value": "4231747395",
                    "evidence_refs": ["ev-w1-detail"],
                },
                "identity": {
                    "operator": "PIONEER NATURAL RES. USA, INC.",
                    "operator_number": "665748",
                    "lease": "GLASSCOCK-DICKENSON 44C",
                    "well": "3H",
                    "county": "MARTIN",
                    "county_code": "317",
                    "permit_number": "0918069",
                },
                "events": [
                    {
                        "kind": "spud",
                        "label": "Drilling started",
                        "date": "2026-09-25",
                        "source": "texas-rrc-w1-detail",
                        "evidence_refs": ["ev-w1-detail"],
                    }
                ],
            },
        }
    )
    assert result["sector"] == "oil_gas"
    assert result["oil_gas"]["spud_date"] == "2026-09-25"
    assert result["oil_gas"]["county"] == "MARTIN"
    assert result["event"]["kind"] == "spud"


def test_original_permit_issue_and_later_amendment_keep_distinct_dates_and_labels():
    item = {"name": "Historical permit", "source_id": "texas-rrc-drilling-permits"}
    add_browse_evidence(
        item,
        {
            "id": "rrc-amended-evidence",
            "source_id": "texas-rrc-drilling-permits",
            "document_number": "0761171",
            "assessment_current": True,
            "abstract": "\n".join(
                [
                    "operator: TRINITY OPERATING (USG), LLC",
                    "operator_number: 870209",
                    "lease: HAUG-KIESCHNICK AC UNIT 33",
                    "well: 1H",
                    "county_code: 283",
                    "date: 2013-04-24",
                    "amended_date: 2026-09-15",
                    "status: Approved",
                ]
            ),
        },
    )
    result = result_metadata({**item, "_browse_rrc_records": item["_browse_rrc_records"]})
    assert result["oil_gas"]["permit_issue_date"] == "2013-04-24"
    assert result["oil_gas"]["permit_amended_date"] == "2026-09-15"
    assert result["event"]["kind"] == "permit_amended"
    assert result["event"]["label"] == "Permit amended"
    assert result["event"]["date"] == "2026-09-15"
