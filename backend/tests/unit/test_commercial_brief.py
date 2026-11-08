from gridlens.domain.commercial_brief import VERSION, build_commercial_brief


def _source(source_id="e-1", date="2026-10-20", text="Electrical installation at one site"):
    return {
        "id": source_id,
        "title": "Dated permit update",
        "url": f"https://example.test/{source_id}",
        "event_date": date,
        "abstract": text,
        "current": True,
    }


def test_unknown_power_timing_and_authority_stay_unknown():
    brief = build_commercial_brief(
        {
            "evidence": [_source()],
            "required_mw": None,
            "start_window": None,
            "duration": None,
            "shortlist_assessment": {
                "eligible": True,
                "why_now": "Permit issued 2026-10-20: electrical installation",
                "scope": "electrical installation",
                "evidence_refs": ["e-1"],
            },
            "contact_actions": [
                {
                    "kind": "email",
                    "href": "mailto:ops@example.test",
                    "name": "Alex",
                    "purchasing_authority": "No buyer authority established",
                }
            ],
        },
        now="2026-11-08T12:00:00Z",
    )
    assert brief["version"] == VERSION
    assert brief["why_now"]["source_date"] == "2026-10-20"
    assert brief["power_need"]["value"] is None
    assert "unknown is not zero" in " ".join(brief["power_need"]["limitations"])
    assert brief["best_contact"]["authority"] == "No buyer authority established"
    assert brief["best_contact"]["deliverability"].startswith("Unknown")
    assert brief["freshness"]["as_of"] == "2026-11-08T12:00:00Z"
    assert brief["freshness"]["source_age_days"] == 19


def test_conflicting_power_and_unmatched_or_conflicting_dates_abstain():
    brief = build_commercial_brief(
        {
            "power_need": {
                "status": "CONFLICT",
                "claims": [
                    {"value": "8 MW", "evidence": {"id": "e-1"}},
                    {"value": "12 MW", "evidence": {"id": "e-2"}},
                ],
            },
            "required_mw": "8 MW",
            "evidence": [_source("e-1", "2026-10-20"), _source("e-2", "2026-10-21")],
            "shortlist_assessment": {
                "eligible": True,
                "why_now": "Permit issued 2026-10-20: electrical work",
                "scope": "electrical work",
                "evidence_refs": ["missing-id"],
            },
        },
        now="2026-11-08",
    )
    assert brief["power_need"]["status"] == "conflict"
    assert brief["power_need"]["value"] is None
    assert brief["why_now"]["text"] is None
    assert brief["why_now"]["source_date"] is None


def test_amount_class_or_claim_without_current_source_never_populates_need():
    brief = build_commercial_brief(
        {
            "required_mw": "8 MW",
            "power_amount_class": "documented",
            "power_need": {"status": "SUPPORTED", "value": "8 MW", "evidence": []},
            "evidence": [_source()],
        }
    )
    assert brief["power_need"]["value"] is None
    assert brief["power_need"]["status"] == "unknown"


def test_stale_or_noncurrent_event_reference_does_not_create_why_now():
    row = _source()
    row["current"] = False
    brief = build_commercial_brief(
        {
            "event": {"kind": "permit_issued", "label": "Permit issued", "date": "2026-10-20", "evidence_refs": ["e-1"]},
            "evidence": [row],
        },
        now="2026-11-08",
    )
    assert brief["why_now"]["text"] is None
    assert brief["why_now"]["sources"] == []


def test_conflicting_current_event_dates_abstain_and_keep_source_records():
    brief = build_commercial_brief(
        {
            "shortlist_assessment": {
                "eligible": True,
                "why_now": "Permit issued 2026-10-20: electric work",
                "scope": "electric work",
                "evidence_refs": ["e-1", "e-2"],
            },
            "evidence": [_source("e-1", "2026-10-20"), _source("e-2", "2026-10-21")],
        },
        now="2026-11-08",
    )
    assert brief["why_now"]["source_date"] is None
    assert brief["why_now"]["text"] is None
    assert len(brief["sources"]) == 2


def test_campus_it_and_nameplate_amounts_never_become_rental_need():
    for summary in (
        "40 MW campus demand",
        "40 MW IT load",
        "40 MW equipment nameplate",
    ):
        brief = build_commercial_brief(
            {"required_mw": "40 MW", "power_summary": summary, "activity": "construction"}
        )
        assert brief["power_need"]["value"] is None
        assert brief["power_need"]["amount_class"] == "unknown"


def test_source_event_requires_exact_evidence_reference_and_scope():
    brief = build_commercial_brief(
        {
            "project_metadata": {
                "event": {
                    "kind": "permit_issued",
                    "label": "Permit issued",
                    "date": "2026-10-20",
                    "evidence_refs": ["e-1"],
                }
            },
            "evidence": [_source(text="Generator replacement")],
        },
        now="2026-11-08",
    )
    assert brief["why_now"]["source_date"] == "2026-10-20"
    assert brief["why_now"]["sources"][0]["evidence_id"] == "e-1"
    assert brief["why_now"]["sources"][0]["url"] is None


def test_generic_contact_is_not_promoted_to_authority_and_action_is_single():
    brief = build_commercial_brief(
        {
            "contact_actions": [
                {"kind": "contact", "href": "https://example.test/contact", "company": "Acme", "responsibility": "General company contact path"},
                {"kind": "email", "href": "mailto:buyer@example.test", "name": "Buyer", "responsibility": "Project contact", "purchasing_authority": "Requires confirmation for this power package"},
            ]
        }
    )
    assert brief["best_contact"]["contact"] == "Buyer"
    assert brief["best_contact"]["route_kind"] == "person_method"
    assert brief["next_action"]["kind"] == "confirm_need"
    assert brief["best_contact"]["authority"] == "Requires confirmation for this power package"


def test_project_aliases_do_not_merge_distinct_need_ids():
    first = build_commercial_brief({"id": "need-a", "name": "Alias A", "required_mw": "2 MW"})
    second = build_commercial_brief({"id": "need-b", "name": "Alias B", "required_mw": "3 MW"})
    assert first["power_need"]["value"] is None
    assert second["power_need"]["value"] is None
    assert first["power_need"]["status"] == second["power_need"]["status"] == "unknown"


def test_supported_amount_requires_source_bearing_claim_and_normalizes_unit():
    brief = build_commercial_brief(
        {
            "required_mw": "500 kW",
            "power_need": {
                "status": "SUPPORTED",
                "value": "500 kW",
                "evidence": [{"id": "e-1", "url": "https://example.test/e-1"}],
            },
        }
    )
    assert brief["power_need"]["value"] == "0.5"
    assert brief["power_need"]["unit"] == "MW"


def test_source_output_omits_raw_excerpts():
    brief = build_commercial_brief({"evidence": [_source(text="secret@example.test") ]})
    assert "abstract" not in brief["sources"][0]
    assert "secret@example.test" not in repr(brief)
