from datetime import date

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
            "event": {
                "kind": "permit_issued",
                "label": "Permit issued",
                "date": "2026-10-20",
                "evidence_refs": ["e-1"],
            },
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
    assert brief["why_now"]["sources"][0]["url"] == "https://example.test/e-1"


def test_generic_contact_is_not_promoted_to_authority_and_action_is_single():
    brief = build_commercial_brief(
        {
            "contact_actions": [
                {
                    "kind": "contact",
                    "href": "https://example.test/contact",
                    "company": "Acme",
                    "responsibility": "General company contact path",
                },
                {
                    "kind": "email",
                    "href": "mailto:buyer@example.test",
                    "name": "Buyer",
                    "responsibility": "Project contact",
                    "purchasing_authority": "Requires confirmation for this power package",
                },
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
            "activity": "construction",
            "power_need": {
                "status": "SUPPORTED",
                "value": "500 kW",
                "scope": "construction",
                "amount_class": "documented",
                "evidence": [
                    {
                        "id": "e-1",
                        "url": "https://example.test/e-1",
                        "content_hash": "a" * 64,
                    }
                ],
            },
            "evidence": [
                {
                    "id": "e-1",
                    "url": "https://example.test/e-1",
                    "content_hash": "a" * 64,
                    "current": True,
                }
            ],
        }
    )
    assert brief["power_need"]["value"] == "0.5"
    assert brief["power_need"]["unit"] == "MW"


def test_source_output_omits_raw_excerpts():
    brief = build_commercial_brief({"evidence": [_source(text="secret@example.test")]})
    assert "abstract" not in brief["sources"][0]
    assert "secret@example.test" not in repr(brief)


def test_power_claim_reference_must_match_current_version_and_url():
    item = {
        "power_need": {
            "status": "SUPPORTED",
            "value": "500 kW",
            "evidence": [{"id": "e-old", "url": "https://example.test/old"}],
        },
        "evidence": [
            {
                "id": "e-new",
                "url": "https://example.test/new",
                "content_hash": "b" * 64,
                "current": True,
            }
        ],
    }
    assert build_commercial_brief(item)["power_need"]["value"] is None


def test_publication_dates_differing_do_not_conflict_with_one_event_date():
    brief = build_commercial_brief(
        {
            "shortlist_assessment": {
                "eligible": True,
                "why_now": "Published 2026-10-20: electric construction",
                "scope": "electric construction",
                "evidence_refs": ["e-1", "e-2"],
            },
            "evidence": [
                {
                    "id": "e-1",
                    "title": "Report A",
                    "url": "https://example.test/a",
                    "published_at": "2026-10-20",
                    "current": True,
                },
                {
                    "id": "e-2",
                    "title": "Report B",
                    "url": "https://example.test/b",
                    "published_at": "2026-10-21",
                    "current": True,
                },
            ],
        },
        now="2026-11-08",
    )
    assert brief["why_now"]["source_date"] == "2026-10-20"
    assert brief["why_now"]["text"].startswith("Published 2026-10-20")
    assert "Conflicting current dates" not in " ".join(brief["limitations"])


def test_future_milestone_does_not_refresh_old_source_publication():
    brief = build_commercial_brief(
        {
            "shortlist_assessment": {
                "eligible": True,
                "why_now": "Published 2026-02-01; expected 2027-01-01 construction start",
                "scope": "construction",
                "evidence_refs": ["e-1"],
            },
            "evidence": [
                {
                    "id": "e-1",
                    "title": "Expected construction schedule",
                    "url": "https://example.test/schedule",
                    "published_at": "2026-02-01",
                    "event_date": "2027-01-01",
                    "event_date_label": "Expected construction start",
                    "current": True,
                }
            ],
        },
        now="2026-11-08",
    )
    assert brief["why_now"]["source_date"] == "2026-02-01"
    assert brief["why_now"]["text"].startswith("Published 2026-02-01:")
    assert brief["freshness"]["source_date"] == "2026-02-01"
    assert brief["freshness"]["source_age_days"] == 280
    assert brief["freshness"]["status"] == "stale_source"


def test_future_publication_date_is_not_reported_as_fresh():
    brief = build_commercial_brief(
        {
            "evidence": [
                {
                    "id": "e-1",
                    "title": "Future-dated source",
                    "url": "https://example.test/future",
                    "published_at": "2027-01-01",
                    "current": True,
                }
            ]
        },
        now="2026-11-08",
    )
    assert brief["freshness"]["source_date"] is None
    assert brief["freshness"]["source_age_days"] is None
    assert brief["freshness"]["status"] == "source_age_unknown"


def test_conflicting_same_event_dates_and_overflow_abstain():
    evidence = [
        {
            "id": f"e-{day}",
            "title": "Event report",
            "url": f"https://example.test/{day}",
            "event_date": f"2026-10-{day}",
            "event_date_label": "construction start",
            "current": True,
        }
        for day in ("20", "21")
    ]
    conflicting = build_commercial_brief(
        {
            "shortlist_assessment": {
                "eligible": True,
                "why_now": "Construction starts 2026-10-20",
                "scope": "construction",
                "evidence_refs": ["e-20", "e-21"],
            },
            "evidence": evidence,
        },
        now="2026-11-08",
    )
    assert conflicting["why_now"]["text"] is None
    assert any("Conflicting current dates" in value for value in conflicting["limitations"])

    overflow = build_commercial_brief(
        {
            "shortlist_assessment": {
                "eligible": True,
                "why_now": "Construction starts",
                "scope": "construction",
                "evidence_refs": ["e-20"],
            },
            "evidence": evidence + [{"overflow": True}],
            "required_mw": "10 MW",
            "power_need": {
                "status": "SUPPORTED",
                "value": "10 MW",
                "amount_class": "documented",
                "evidence": [{"id": "e-20", "url": "https://example.test/20"}],
            },
        },
        now="2026-11-08",
    )
    assert overflow["why_now"]["text"] is None
    assert overflow["power_need"]["value"] is None


def test_accepted_source_demand_projects_only_with_matching_activity_scope():
    evidence_hash = "a" * 64
    semantic_hash = "b" * 64
    from gridlens.domain.project_research import VERSION as RESEARCH_VERSION
    from gridlens.domain.project_research import extract_project_claims
    from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION

    quote = "Orion Data Center construction requires 500 kW."
    project_id = "00000000-0000-0000-0000-000000000001"
    need_id = "00000000-0000-0000-0000-000000000002"
    claims = extract_project_claims(
        quote,
        references=["Orion Data Center"],
        activity_key="construction",
        published_at=date(2026, 10, 20),
        today=date(2026, 11, 8),
    )
    retained_claim = {
        **claims[0],
        "project_id": project_id,
        "need_id": need_id,
        "evidence_id": "e-1",
        "evidence_hash": evidence_hash,
    }
    item = {
        "id": need_id,
        "project_id": project_id,
        "name": "Orion Data Center",
        "location": "Austin, TX",
        "activity": "construction",
        "evidence": [
            {
                "id": "e-1",
                "title": "Project electrical demand report",
                "abstract": quote,
                "url": "https://example.test/e-1",
                "content_hash": evidence_hash,
                "semantic_hash": semantic_hash,
                "observation_hash": semantic_hash,
                "evaluator_version": RESEARCH_VERSION,
                "project_identity_key": "site-1",
                "assessment": {
                    "semantic_hash": semantic_hash,
                    "evidence_hash": evidence_hash,
                    "project_identity_key": "site-1",
                    "acquisition_capture_version": CAPTURE_VERSION,
                    "admission_status": "project_research_supplement",
                    "target_need_id": need_id,
                    "research_claims": [retained_claim],
                },
                "published_at": date(2026, 10, 20),
                "observed_at": "2026-10-21T00:00:00+00:00",
                "current": True,
            }
        ],
    }
    brief = build_commercial_brief(item, now="2026-11-08")
    assert brief["power_need"]["value"] == "0.5"
    assert brief["power_need"]["unit"] == "MW"
    assert brief["power_need"]["scope"] == "construction"
    assert brief["power_need"]["amount_class"] == "documented"

    scoped_conflict = build_commercial_brief(
        {
            **item,
            "power_need": {
                "status": "SUPPORTED",
                "value": "0.5 MW",
                "scope": "IT capacity",
                "amount_class": "documented",
                "evidence": [
                    {
                        "id": "e-1",
                        "url": "https://example.test/e-1",
                        "content_hash": evidence_hash,
                    }
                ],
            },
        }
    )
    assert scoped_conflict["power_need"]["value"] is None
    assert any(
        "scope does not match" in value for value in scoped_conflict["power_need"]["limitations"]
    )


def test_project_event_date_must_match_its_current_citation():
    brief = build_commercial_brief(
        {
            "event": {
                "kind": "commissioning",
                "label": "Commissioning starts",
                "date": "2030-01-01",
                "evidence_refs": ["e-1"],
            },
            "evidence": [
                {
                    "id": "e-1",
                    "title": "Permit issued",
                    "url": "https://example.test/permit",
                    "event_date": "2026-10-20",
                    "event_date_label": "Permit issued",
                    "current": True,
                }
            ],
        },
        now="2026-11-08",
    )
    assert brief["why_now"]["text"] is None
    assert brief["why_now"]["sources"] == []
    assert any("does not match" in value for value in brief["limitations"])


def test_fallback_event_with_conflicting_bound_dates_abstains():
    brief = build_commercial_brief(
        {
            "event": {
                "kind": "construction",
                "label": "Construction",
                "evidence_refs": ["e-1", "e-2"],
            },
            "evidence": [
                {
                    "id": "e-1",
                    "title": "Site update",
                    "url": "https://example.test/1",
                    "event_date": "2026-10-20",
                    "event_date_label": "Construction started",
                    "published_at": "2026-10-20",
                    "current": True,
                },
                {
                    "id": "e-2",
                    "title": "Site update",
                    "url": "https://example.test/2",
                    "event_date": "2026-10-21",
                    "event_date_label": "Construction started",
                    "published_at": "2026-10-22",
                    "current": True,
                },
            ],
        },
        now="2026-11-08",
    )
    assert brief["why_now"]["text"] is None
    assert brief["why_now"]["sources"] == []
    assert any("Conflicting current dates" in value for value in brief["limitations"])
