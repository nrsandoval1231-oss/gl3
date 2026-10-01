import pytest

from gridlens.intelligence.briefs import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    _fact_options,
    _response_schema,
    _safe_fact_text,
    _validate_result,
    brief_view,
)


def test_model_selects_curated_facts_and_server_renders_brief():
    evidence = {
        "evidence-a": {
            "title": "Dallas issued commercial new-construction permit 12345",
            "excerpt": (
                "event: Issued\nwork: Commercial\nproposed_land_use: Warehouse\n"
                "description: Commercial new construction of a warehouse"
            ),
            "url": "https://example.test/permit",
            "publisher": "City",
        }
    }
    facts = _fact_options(evidence)
    selected = next(key for key in facts if key.endswith("proposed-land-use"))
    result, citations = _validate_result(
        {"selected_fact_ids": [selected], "hypothesis_fact_id": selected},
        facts,
        ["Activity-specific power requirement remains unknown."],
    )
    assert result["event_summary"] == [
        {"text": "Permit-listed proposed land use: Warehouse.", "evidence_id": "evidence-a"}
    ]
    assert result["commercial_hypothesis"]["text"] == (
        "Investigation hypothesis: Does warehouse construction require temporary site power?"
    )
    assert "power requirement remains unknown" in result["unknowns"][0]
    assert result["next_step"].startswith("Ask the project contact")
    assert citations[0]["excerpt"] == "proposed_land_use: Warehouse"
    assert (POLICY_VERSION, SCHEMA_VERSION) == (
        "power-need-brief-v4",
        "power-need-brief-schema-v3",
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"selected_fact_ids": [], "hypothesis_fact_id": "missing"},
        {"selected_fact_ids": ["missing"], "hypothesis_fact_id": "missing"},
        {
            "selected_fact_ids": ["evidence-a:description"] * 2,
            "hypothesis_fact_id": "evidence-a:description",
        },
        {
            "selected_fact_ids": ["evidence-a:description"],
            "hypothesis_fact_id": "evidence-a:proposed-land-use",
        },
        {
            "selected_fact_ids": ["evidence-a:description", "evidence-a:source-event", "third"],
            "hypothesis_fact_id": "evidence-a:description",
        },
    ],
)
def test_model_cannot_invent_facts_or_select_unbounded_outputs(raw):
    facts = _fact_options(
        {
            "evidence-a": {
                "title": "Permit record",
                "excerpt": "proposed_land_use: Warehouse\ndescription: New warehouse construction",
                "url": "https://example.test/permit",
                "publisher": "City",
            }
        }
    )
    with pytest.raises(ValueError, match="invalid_fact_selection"):
        _validate_result(raw, facts, [])


def test_dallas_live_quality_failure_renders_only_supported_roles_and_facts():
    source = {
        "title": "Dallas issued commercial new-construction permit 2210211015_174492520-001",
        "excerpt": (
            "event: Issued\ntype: Commercial New Construction Permit\nwork: Commercial\n"
            "proposed_land_use: Warehouse\ndescription: Commercial New Construction Permit; "
            "Proposed Land Use: Warehouse; Type of Work: Commercial\n"
            "contact_type: Applicant\napplicant_full_name: Robert Akins\n"
            "lp_business_name: TRICORE BUILDERS INC"
        ),
        "url": "https://example.test/dallas",
        "publisher": "City of Dallas",
    }
    facts = _fact_options({"dallas": source})
    with pytest.raises(ValueError, match="invalid_schema"):
        _validate_result(
            {
                "event_summary": [
                    {
                        "text": "A project led by TRICORE with applicant Robert Akins at  ̶ ."
                    }
                ],
                "commercial_hypothesis": {
                    "text": "Investigation hypothesis: demand is indicated."
                },
            },
            facts,
            [],
        )
    selected = [key for key in facts if key.endswith(("proposed-land-use", "lp-business-name"))]
    result, citations = _validate_result(
        {"selected_fact_ids": selected, "hypothesis_fact_id": selected[0]}, facts, []
    )
    output = " ".join(item["text"] for item in result["event_summary"])
    assert "project led by" not in output.casefold()
    assert "TRICORE BUILDERS INC (role unverified)" in output
    assert "Robert Akins" not in output
    assert "warehouse construction" in result["commercial_hypothesis"]["text"].casefold()
    assert "2210211015" not in output
    assert len(citations) == 1


def test_houston_live_quality_failure_renders_source_description_without_blank_slots():
    source = {
        "title": "Houston sold permit 26051624 — Building Pmt",
        "excerpt": "description: 2,765 SQ. FT. CONVERT TO LABORATORY 1-1-5-B-B 2021 IBC",
        "url": "https://example.test/houston",
        "publisher": "City of Houston Permitting Center",
    }
    facts = _fact_options({"houston": source})
    with pytest.raises(ValueError, match="invalid_schema"):
        _validate_result(
            {
                "event_summary": [
                    {
                        "text": "Permit sold for converting  ,  to laboratory space under "
                        "building code."
                    }
                ],
                "commercial_hypothesis": {
                    "text": "Investigation hypothesis: activity potentially impacts power needs."
                },
            },
            facts,
            [],
        )
    selected = next(iter(facts))
    result, citations = _validate_result(
        {"selected_fact_ids": [selected], "hypothesis_fact_id": selected}, facts, []
    )
    text = result["event_summary"][0]["text"]
    assert "converting  ," not in text
    assert "laboratory" in text.casefold()
    assert "laboratory conversion" in result["commercial_hypothesis"]["text"].casefold()
    assert citations[0]["excerpt"] == source["excerpt"]


def test_unstructured_source_has_exact_quote_fallback_and_neutral_question():
    facts = _fact_options(
        {
            "news": {
                "title": "Regional cultivation application advances",
                "excerpt": "The public report says the application advanced to review.",
                "url": "https://example.test/news",
                "publisher": "Public report",
            }
        }
    )
    selected = next(iter(facts))
    result, citations = _validate_result(
        {"selected_fact_ids": [selected], "hypothesis_fact_id": selected}, facts, []
    )
    assert result["event_summary"][0]["text"] == f"Source excerpt: {facts[selected]['excerpt']}"
    assert result["commercial_hypothesis"]["text"] == (
        "Investigation hypothesis: Does activity described in this source require "
        "temporary site power?"
    )
    assert citations[0]["excerpt"] in facts[selected]["excerpt"]


def test_schema_only_allows_bounded_server_fact_selections():
    facts = {
        "evidence-a:description": {"text": "Source description: Construction."},
        "evidence-b:source-event": {"text": "Source event listed as issued."},
    }
    schema = _response_schema(facts)
    properties = schema["properties"]
    assert properties["selected_fact_ids"]["minItems"] == 1
    assert properties["selected_fact_ids"]["maxItems"] == 2
    assert properties["selected_fact_ids"]["items"]["enum"] == sorted(facts)
    assert properties["hypothesis_fact_id"]["enum"] == sorted(facts)


def test_malformed_placeholders_and_combining_marks_are_not_rendered():
    assert not _safe_fact_text("Permit sold for converting  ,  to laboratory space")
    assert not _safe_fact_text("A description with a combining mark:  ̶ ")


def test_cached_result_is_stale_when_current_input_is_unavailable():
    class Row:
        result = {"event_summary": []}
        generated_fingerprint = "old"
        status = "ready"
        generated_at = None
        citations = []
        error = None
        input_tokens = output_tokens = 0

    result = brief_view(Row(), fingerprint=None)
    assert result["status"] == "stale"
    assert result["stale"] is True
