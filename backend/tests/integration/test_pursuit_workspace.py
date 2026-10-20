"""Saved need-level workspace tests over an isolated disposable PostgreSQL schema."""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from gridlens.intelligence.pursuit_workspace import page
from gridlens.intelligence.saved_browse import rebuild
from gridlens.persistence.models import BrowseRow

pytest_plugins = ["test_saved_browse"]


def test_workspace_filters_counts_paginates_and_binds_token(saved_db, monkeypatch):
    from test_saved_browse import seed

    from gridlens.domain import commercial_triage

    seed(saved_db, count=55, histories=1)
    evaluated = {}
    canonical_build = commercial_triage.build_card

    def capture(item, chain, today):
        result = canonical_build(item, chain, today)
        evaluated[str(item["id"])] = result
        return result

    monkeypatch.setattr(commercial_triage, "build_card", capture)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        rows = list(session.scalars(select(BrowseRow).order_by(BrowseRow.need_id)))
        for row in rows:
            preview = evaluated[str(row.need_id)]
            assert row.compact["commercial_preview"] == {
                "disposition": preview["disposition"],
                "reason": preview["reason"],
                "next_question": preview["next_question"],
                "next_action": preview["next_action"],
                "organization": preview["organization"],
            }
    filters = {
        "search": "",
        "tier": "Signal",
        "disposition": None,
        "geography": None,
        "industry": None,
        "activity": None,
        "timing": None,
        "mw_status": None,
        "mw_min": None,
        "mw_max": None,
        "sort": "priority",
    }
    with saved_db() as session:
        statements = []

        def capture(_connection, _cursor, statement, *_args):
            if "browse_rows" in statement.lower():
                statements.append(statement.lower())

        event.listen(saved_db.kw["bind"], "before_cursor_execute", capture)
        first = page(session, filters, limit=50, offset=0, token=None)
        second = page(
            session,
            filters,
            limit=50,
            offset=first["next_offset"],
            token=first["cohort_token"],
        )
        assert first["total"] == 55
        assert len(first["items"]) == 50
        assert len(second["items"]) == 5
        assert first["counts"] == {"action_now": 0, "research": 0, "watch": 55, "reject": 0}
        assert first["count_unit"] == "power needs"
        assert first["changes_available"] is False
        assert all(
            item["required_mw"] is None and item["supply"] == "Unknown" for item in first["items"]
        )
        assert first["items"][0]["commercial_reason"]
        assert statements and all("generation_id" in statement for statement in statements)
        selected = page(
            session,
            {**filters, "disposition": "WATCH"},
            limit=50,
            offset=0,
            token=None,
        )
        assert selected["total"] == 55
        assert selected["counts"]["watch"] == 55
        by_mw = page(session, {**filters, "sort": "mw"}, limit=50, offset=0, token=None)
        assert all(item["required_mw"] is None for item in by_mw["items"])
        huge_bound = page(
            session,
            {**filters, "mw_min": "1e1000"},
            limit=50,
            offset=0,
            token=None,
        )
        assert huge_bound["total"] == 0
        with pytest.raises(HTTPException) as error:
            page(
                session,
                {**filters, "activity": "other"},
                limit=50,
                offset=50,
                token=first["cohort_token"],
            )
        assert error.value.status_code == 409


def test_workspace_rejects_missing_preview_and_missing_generation(saved_db, monkeypatch):
    from test_saved_browse import seed

    from gridlens.intelligence import pursuit_workspace

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        row = session.scalar(select(BrowseRow).limit(1))
        row.compact = {
            key: value for key, value in row.compact.items() if key != "commercial_preview"
        }
    filters = {
        "search": "",
        "tier": None,
        "disposition": None,
        "geography": None,
        "industry": None,
        "activity": None,
        "timing": None,
        "mw_status": None,
        "mw_min": None,
        "mw_max": None,
        "sort": "priority",
    }
    with saved_db() as session, pytest.raises(HTTPException) as error:
        page(session, filters, limit=50, offset=0, token=None)
    assert error.value.status_code == 503
    monkeypatch.setattr(
        pursuit_workspace,
        "current_generation",
        lambda _session: (_ for _ in ()).throw(HTTPException(503, "saved generation unavailable")),
    )
    with saved_db() as session, pytest.raises(HTTPException) as missing:
        page(session, filters, limit=50, offset=0, token=None)
    assert missing.value.status_code == 503


def test_workspace_facets_unknowns_and_stable_sort_use_saved_row_fixture(saved_db):
    """Synthetic scalar distribution exercises read-model query behavior only."""
    from test_saved_browse import seed

    seed(saved_db, count=55, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    dispositions = ("ACTION NOW", "RESEARCH", "WATCH", "REJECT")
    tiers = ("Signal", "Prospect", "Lead")
    expected_rows = []
    with saved_db.begin() as session:
        rows = list(session.scalars(select(BrowseRow).order_by(BrowseRow.need_id)))
        for index, row in enumerate(rows):
            tier = tiers[index % len(tiers)]
            disposition = dispositions[index % len(dispositions)]
            location = "" if index % 5 == 0 else "dallas, tx"
            industry = "unknown" if index % 7 == 0 else "construction"
            activity = "" if index % 6 == 0 else "construction"
            known_mw = index % 3 != 0
            has_timing = index % 2 == 0
            row.tier = tier
            row.location = location
            row.industry = industry
            row.activity = activity
            row.has_timing = has_timing
            row.mw_low = Decimal("1.5") if known_mw else None
            row.mw_high = Decimal("2.5") if known_mw else None
            row.commercial_segment = 1
            row.commercial_geography = 1
            row.commercial_date = 1
            row.project_id = UUID(int=1)
            row.compact = {
                **row.compact,
                "tier": tier,
                "location": location or None,
                "industry": industry,
                "activity": activity or None,
                "required_mw": "1.5-2.5 MW" if known_mw else None,
                "start_window": "2026-11" if has_timing else None,
                "commercial_preview": {
                    **row.compact["commercial_preview"],
                    "disposition": disposition,
                },
            }
            expected_rows.append(
                (
                    str(row.need_id),
                    tier,
                    disposition,
                    location,
                    industry,
                    activity,
                    known_mw,
                    has_timing,
                )
            )

    base_filters = {
        "search": "",
        "tier": None,
        "disposition": None,
        "geography": None,
        "industry": None,
        "activity": None,
        "timing": None,
        "mw_status": None,
        "mw_min": None,
        "mw_max": None,
        "sort": "priority",
    }
    with saved_db() as session:
        whole = page(session, base_filters, limit=50, offset=0, token=None)
        assert whole["counts"] == {
            "action_now": 14,
            "research": 14,
            "watch": 14,
            "reject": 13,
        }
        for tier in tiers:
            selection = page(
                session,
                {**base_filters, "tier": tier},
                limit=50,
                offset=0,
                token=None,
            )
            assert selection["total"] == sum(row[1] == tier for row in expected_rows)
        for disposition in dispositions:
            selection = page(
                session,
                {**base_filters, "disposition": disposition},
                limit=50,
                offset=0,
                token=None,
            )
            assert selection["total"] == sum(row[2] == disposition for row in expected_rows)
            assert selection["counts"] == whole["counts"]
        composed = page(
            session,
            {**base_filters, "tier": "Prospect", "disposition": "RESEARCH"},
            limit=50,
            offset=0,
            token=None,
        )
        expected_composed = sum(
            row[1] == "Prospect" and row[2] == "RESEARCH" for row in expected_rows
        )
        assert composed["total"] == expected_composed
        assert composed["counts"] == {
            key: sum(
                row[1] == "Prospect" and row[2] == key.upper().replace("_", " ")
                for row in expected_rows
            )
            for key in ("action_now", "research", "watch", "reject")
        }
        known = page(
            session,
            {**base_filters, "mw_status": "KNOWN"},
            limit=50,
            offset=0,
            token=None,
        )
        unknown = page(
            session,
            {**base_filters, "mw_status": "UNKNOWN"},
            limit=50,
            offset=0,
            token=None,
        )
        assert known["total"] == sum(row[6] for row in expected_rows)
        assert unknown["total"] == sum(not row[6] for row in expected_rows)
        timed = page(
            session,
            {**base_filters, "timing": "KNOWN"},
            limit=50,
            offset=0,
            token=None,
        )
        assert timed["total"] == sum(row[7] for row in expected_rows)
        unknown_geo = page(
            session,
            {**base_filters, "geography": "UNKNOWN"},
            limit=50,
            offset=0,
            token=None,
        )
        assert unknown_geo["total"] == sum(not row[3] for row in expected_rows)
        unknown_industry = page(
            session,
            {**base_filters, "industry": "UNKNOWN"},
            limit=50,
            offset=0,
            token=None,
        )
        assert unknown_industry["total"] == sum(row[4] == "unknown" for row in expected_rows)
        unknown_activity = page(
            session,
            {**base_filters, "activity": "UNKNOWN"},
            limit=50,
            offset=0,
            token=None,
        )
        assert unknown_activity["total"] == sum(not row[5] for row in expected_rows)
        ordered_first = page(session, base_filters, limit=50, offset=0, token=None)
        ordered_second = page(
            session,
            base_filters,
            limit=50,
            offset=50,
            token=ordered_first["cohort_token"],
        )
        ordered_ids = [item["id"] for item in ordered_first["items"] + ordered_second["items"]]
        assert ordered_ids == sorted(row[0] for row in expected_rows)
        assert len(set(ordered_ids)) == 55


def test_workspace_route_rejects_bad_sort_unknown_parameter_and_huge_mw(saved_db):
    from datetime import UTC, datetime

    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.security import token_for

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert client.get("/api/opportunities/workspace?sort=unsupported").status_code == 422
    assert client.get("/api/opportunities/workspace?unknown=1").status_code == 422
    response = client.get("/api/opportunities/workspace?mw_min=1e1000")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0


def test_workspace_route_requires_authentication():
    from gridlens.api import app as api

    client = TestClient(api.app, base_url="https://testserver")
    response = client.get("/api/opportunities/workspace")
    assert response.status_code == 401


def test_signal_decision_counts_cover_all_pages_of_active_signal_cohort(monkeypatch):
    from gridlens.api import app as api

    pages = {
        0: [{"signal_display_decision": "SHOW"} for _ in range(50)],
        50: [
            {"signal_display_decision": "REVIEW"},
            {"signal_display_decision": None},
        ],
    }
    requested_offsets = []

    def opportunity_page(*, tier, limit, offset):
        assert tier == "Signal" and limit == 50
        requested_offsets.append(offset)
        return pages.get(offset, [])

    monkeypatch.setattr(api, "opportunities", opportunity_page)
    assert api.signal_decision_counts() == {
        "show": 50,
        "review": 1,
        "hold": 0,
        "unadjudicated": 1,
    }
    assert requested_offsets == [0, 50]
