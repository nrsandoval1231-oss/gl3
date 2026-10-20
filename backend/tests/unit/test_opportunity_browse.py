from importlib import import_module
from uuid import uuid4

import pytest
from fastapi import HTTPException

from gridlens.api.app import _MAX_SAVED_SNAPSHOT_BYTES, _check_saved_history_bounds
from gridlens.intelligence.opportunity_browse import (
    add_browse_evidence,
    cohort_token,
    grouped_opportunities,
    grouped_signal_decision,
    matched_opportunity,
    normalized,
    opportunity_group_id,
    project_title,
)


def _item(*, need_id=None, project_id=None, action="", source="city-building-permits"):
    return {
        "id": need_id or uuid4(),
        "project_id": project_id,
        "tier": "Signal",
        "name": "Permit project",
        "location": "Chicago",
        "activity": "facility-expansion",
        "supported_action": action,
        "evidence": [{"source_id": source, "document_number": "P-1"}],
    }


def test_shared_project_grouping_uses_full_cohort_and_stable_opaque_id():
    project_id = uuid4()
    first = _item(project_id=project_id)
    second = _item(project_id=project_id)

    groups = grouped_opportunities([first, second])

    assert len(groups) == 1
    assert len(groups[0][1]) == 2
    assert opportunity_group_id(groups[0][0]) == opportunity_group_id(groups[0][0])
    assert "Permit project" not in opportunity_group_id(groups[0][0])


def test_permit_event_grouping_requires_explicit_place_and_date_identity():
    action = "Install temporary service in South Campus on September 12, 2026"
    first = _item(action=action)
    second = _item(action=action)
    unrelated = _item(action="Install temporary service in North Campus on September 12, 2026")

    groups = grouped_opportunities([first, second, unrelated])

    assert sorted(len(members) for _, members in groups) == [1, 2]


def test_matcher_normalizes_full_width_text_and_retains_member_result():
    member = _item()
    assert normalized("  ＣＨＩＣＡＧＯ  ") == "chicago"
    assert matched_opportunity(member, "Chicago")
    assert not matched_opportunity(member, "Milwaukee")
    assert matched_opportunity(member, "retained source phrase", evidence_text_match=True)


def test_matcher_preserves_matches_across_joined_search_field_boundaries():
    member = _item(source="other-source")
    member.update(
        name="Synthetic project",
        location="Chicago",
        activity="facility",
        supported_subject="permit",
    )

    assert matched_opportunity(member, "chicago facility permit")


@pytest.mark.parametrize(
    ("name", "query", "expected"),
    [
        ("\ufeffData\ufeffCenter", "data center", True),
        ("Data\x1cCenter", "data center", False),
        ("Data\u2003Center", "data center", True),
        ("ＤＡＴＡ　ＣＥＮＴＥＲ", "data center", True),
        ("Straße", "STRASSE", False),
        ("ΟΣ", "οσ", False),
        ("ΟΣ", "ΟΣ", True),
        ("İSTANBUL", "istanbul", False),
        ("İSTANBUL", "i\u0307stanbul", True),
        ("oﬃce", "office", True),
        ("Data\t\r\n Center", "  data   center  ", True),
    ],
)
def test_matcher_normalization_matches_frozen_typescript_whitespace_and_case(name, query, expected):
    item = _item()
    item["name"] = name

    assert matched_opportunity(item, query) is expected


def test_cohort_token_binds_filter_order_and_row_version():
    row = {"id": "need-1", "_cohort_version": "v1"}
    base = cohort_token({"tier": "Signal"}, [row], ["project:Signal:p1"])

    assert base == cohort_token({"tier": "signal"}, [row], ["project:Signal:p1"])
    assert base != cohort_token(
        {"tier": "Signal"}, [{**row, "_cohort_version": "v2"}], ["project:Signal:p1"]
    )
    assert base != cohort_token({"tier": "Signal"}, [row], ["project:Signal:p2"])


def test_browse_route_defaults_remain_plain_values_for_direct_callers():
    api = import_module("gridlens.api.app")

    assert api.opportunities.__defaults__[3:6] == (50, 0, None)
    assert api.opportunity_group_page.__defaults__[-2:] == (50, 0)
    assert api.export_opportunities_csv.__defaults__[-1] == 500
    assert api.commercial_triage.__defaults__ == (50, 0)
    assert api.commercial_triage_history.__defaults__ == (50, 0)


def test_grouped_signal_decision_preserves_existing_precedence_and_unknown_review():
    assert (
        grouped_signal_decision(
            [{"signal_display_decision": "HOLD"}, {"signal_display_decision": "SHOW"}]
        )
        == "SHOW"
    )
    assert (
        grouped_signal_decision(
            [{"signal_display_decision": "HOLD"}, {"signal_display_decision": None}]
        )
        == "REVIEW"
    )
    assert grouped_signal_decision([{"signal_display_decision": "HOLD"}]) == "HOLD"


def test_saved_snapshot_preflight_rejects_one_oversized_nested_value():
    row = type("SavedRow", (), {})()
    row.identity_key = "commercial-need:synthetic"
    row.snapshot = {"commercial_triage": {"saved_card": {"notes": ["x"]}}}
    row.snapshot["commercial_triage"]["saved_card"]["notes"] = ["x" * _MAX_SAVED_SNAPSHOT_BYTES]

    with pytest.raises(HTTPException) as oversized:
        _check_saved_history_bounds(row, note_count=1)

    assert oversized.value.status_code == 413
    assert oversized.value.detail["resource"] == "saved_snapshot_bytes"


def _rrc_browse_item(*, title_company=None, title_company_role=None):
    item = _item(source="texas-rrc-drilling-permits")
    item["title_company"] = title_company
    item["title_company_role"] = title_company_role
    return item


def _rrc_evidence(abstract, *, source="texas-rrc-drilling-permits", current=True):
    return {"source_id": source, "abstract": abstract, "assessment_current": current}


def test_browse_title_displays_only_current_official_rrc_operator_with_unknown_authority():
    item = _rrc_browse_item()
    add_browse_evidence(item, _rrc_evidence("row: 0917090\noperator: DE CENTRAL OPERATING, LLC"))

    assert project_title(item) == (
        "DE CENTRAL OPERATING, LLC · RRC permit-listed operator · buyer authority UNKNOWN"
    )


@pytest.mark.parametrize(
    "abstract",
    [
        "row: 123\noperator: \noperator_number: 456\nlease: TEST",
        "row: 123\noperator:   \nlease:   TEST",
        "row: 123\r\noperator: \r\noperator_number: 456\r\nlease: TEST",
    ],
)
def test_browse_title_does_not_read_next_rrc_field_as_blank_operator(abstract):
    item = _rrc_browse_item()
    add_browse_evidence(item, _rrc_evidence(abstract))

    title = project_title(item)
    assert "RRC permit-listed operator" not in title
    assert "456" not in title
    assert "TEST" not in title


@pytest.mark.parametrize(
    "evidence",
    [
        _rrc_evidence("operator: Example Operator", current=False),
        _rrc_evidence("operator: Example Operator", source="company-news"),
        _rrc_evidence("operator: Unknown"),
        _rrc_evidence("operator: N/A"),
        _rrc_evidence("operator: Example Operator\noperator: Other Operator"),
    ],
)
def test_browse_title_rejects_stale_wrong_source_placeholder_and_conflicting_rrc_names(evidence):
    item = _rrc_browse_item()
    add_browse_evidence(item, evidence)

    assert project_title(item) == "Facility expansion · Chicago"


def test_browse_title_preserves_verified_title_company_precedence_over_rrc_operator():
    item = _rrc_browse_item(
        title_company="Verified Buyer", title_company_role="permit-listed owner / occupant"
    )
    add_browse_evidence(item, _rrc_evidence("operator: Example Operator"))

    assert project_title(item) == "Verified Buyer · permit-listed owner / occupant"


def test_browse_title_leaves_conflicting_current_rrc_evidence_unresolved():
    item = _rrc_browse_item()
    add_browse_evidence(item, _rrc_evidence("operator: Example Operator"))
    add_browse_evidence(item, _rrc_evidence("operator: Different Operator"))

    assert project_title(item) == "Facility expansion · Chicago"
