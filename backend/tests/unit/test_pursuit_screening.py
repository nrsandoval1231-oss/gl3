from datetime import date

import pytest

from gridlens.domain.pursuit_screening import screen, work_identity
from gridlens.intelligence.pursuits import _snapshot, _tabs_match, registration_query

AUSTIN = "austin-building-permits"
TODAY = date(2026, 10, 1)


def facts(description="800A temporary service construction power", **extra):
    return {
        "description": description,
        "date": "2026-08-31",
        "status": "Active",
        "address": "100 ORION LN",
        "contractor_company_name": "Orion Electrical",
        "contractor_full_name": "Pat Orion",
        "contractor_phone": "5125550100",
        **extra,
    }


def group(data=None, source=AUSTIN):
    data = data or facts()
    return {
        "site": data["address"],
        "facts": [data],
        "source_id": source,
        "records": [
            {
                "external_id": "2026-100001 EP",
                "url": "https://example.invalid/permit",
                "title": "Synthetic permit",
                "text": data["description"],
                "observed_at": "2026-10-01T03:00:00+00:00",
                "published_at": None,
                "hash": "a",
            }
        ],
        "screen": screen([data], source, TODAY),
    }


def test_explicit_scope_beats_transformers_without_inferred_mw_or_delay():
    explicit = screen([facts()], AUSTIN, TODAY)
    transformer = screen([facts("Expand Data Center with 2 AE Transformers")], AUSTIN, TODAY)
    assert explicit["scope_priority"] > transformer["scope_priority"]
    result = _snapshot(group(), [], {}, [])
    assert result["action_status"] == "Call now"
    assert result["rank_key"][3] == 0  # Fuel unverified.
    assert result["fuel_facts"] == []
    assert all("no MW conversion" in item for item in result["load_facts"])
    assert result["tier"] == "Signal"
    person = result["people"][0]
    assert person["purchasing_authority"] == "Unknown"
    assert "unverified" in person["corporate_role"]
    assert "unverified" in person["project_assignment"]
    assert "routing" in result["contacts"][0]["label"]


def test_new_utility_work_is_screened_without_prioritizing_routine_pad_replacement():
    new_work = screen(
        [facts("New construction: install new transformer for initial energization")],
        AUSTIN,
        TODAY,
    )
    replacement = screen(
        [facts("Interior remodel of existing offices and replace transformer pad")],
        AUSTIN,
        TODAY,
    )
    assert new_work["scope_priority"] == 2
    assert "rental demand remain unknown" in new_work["ranking_reasons"][0]
    assert replacement["scope_priority"] == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"contractor_company_name": "Orion Equipment Rentals"},
        {"status": "Finaled"},
        {"description": "Temporary power package fully awarded"},
        {"description": "Routine repair only"},
        {"date": "2020-01-01"},
    ],
)
def test_negative_evidence_suppresses_even_explicit_scope(extra):
    value = facts(**extra)
    assert screen([value], AUSTIN, TODAY)["drop_reason"]
    assert _snapshot(group(value), [], {}, [])["action_status"] == "Drop"


def test_parent_trade_scope_groups_but_company_and_address_alone_do_not():
    assert work_identity(AUSTIN, "2026-100001 EP", "100 ORION LN") == work_identity(
        AUSTIN, "2026-100001 BP", "100 ORION LN"
    )
    assert work_identity(AUSTIN, "2026-100001 EP", "100 ORION LN BLDG 1") != work_identity(
        AUSTIN, "2026-100001 BP", "100 ORION LN BLDG 2"
    )
    assert work_identity(AUSTIN, "2026-100001 EP", "100 ORION LN") != work_identity(
        AUSTIN, "2026-100002 EP", "100 ORION LN"
    )


def test_rrc_amendment_is_not_startup_fuel_or_rental_claim():
    value = facts(
        "W-1 well permit: Drill; lease ORION SWD, well 1.",
        lease="ORION SWD",
        operator="Orion Operator",
        date="2025-09-29",
        amended_date="2026-09-25",
        contractor_company_name="",
        contractor_full_name="",
        contractor_phone="",
    )
    result = _snapshot(group(value, "texas-rrc-drilling-permits"), [], {}, [])
    assert result["action_status"] == "Monitor"
    assert "2025-09-29" in result["trigger_date"] and "2026-09-25" in result["trigger_date"]
    assert "not a new construction start" in result["trigger_date"]
    assert result["load_facts"] == result["fuel_facts"] == []
    assert any("not an injection operating authorization" in item for item in result["unknowns"])


def test_address_research_does_not_merge_different_buildings():
    assert registration_query("6301 E STASSNEY LN BLDG 8") == "6301 stassney"
    assert (
        _tabs_match("6301 E STASSNEY LN BLDG 8", {"address": "6301 Stassney Lane Building 9"})[0]
        is False
    )
    assert (
        _tabs_match("6301 E STASSNEY LN BLDG 8", {"address": "7301 Stassney Lane Building 8"})[0]
        is False
    )


def test_selected_contractor_cannot_borrow_another_contractors_phone():
    g = group(facts(contractor_phone=""))
    other = facts(contractor_company_name="Other Electric", contractor_phone="5125550200")
    g["facts"].append(other)
    g["records"].append({**g["records"][0], "external_id": "2026-100001 BP"})
    result = _snapshot(g, [], {}, [])
    assert result["organization"] == "Orion Electrical"
    assert result["action_status"] != "Call now"
    assert all(c["organization"] != result["organization"] for c in result["contacts"])


def test_jev_retry_requests_each_consume_budget(monkeypatch):
    import httpx

    from gridlens.intelligence import signal_adjudication as jev

    state = dict.fromkeys(
        [
            "title",
            "abstract",
            "url",
            "published_at",
            "source_id",
            "source_family",
            "publisher",
            "event_date",
            "event_date_label",
            "project_name",
            "location",
            "asset_type",
            "lifecycle_state",
        ],
        "Synthetic test",
    )
    requests, debits = [], []

    def post(*args, **kwargs):
        requests.append(1)
        return httpx.Response(
            429, request=httpx.Request("POST", "https://api.typesafe.ai/v1/systemone")
        )

    def debit():
        if len(debits) >= 2:
            raise RuntimeError("Synthetic request budget exhausted")
        debits.append(1)

    monkeypatch.setattr(jev.httpx, "post", post)
    monkeypatch.setattr(jev.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="request budget exhausted"):
        jev._jev_call(state, "synthetic-key", on_request=debit)
    assert len(requests) == len(debits) == 2
