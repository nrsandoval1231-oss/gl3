"""Page scope the customer-project JSON payload without changing page semantics."""

import json
import re
from uuid import UUID

from rollup_scale_fixture import seed_scale_corpus
from sqlalchemy import event, text
from test_saved_browse import saved_db  # noqa: F401,F811

from gridlens.intelligence import customer_results
from gridlens.intelligence.customer_results import groups
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseGeneration,
    BrowseRow,
    BrowseState,
    CompanyIdentity,
)

pytest_plugins = ["test_saved_browse"]


def _walk(plan):
    stack = [plan]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.get("Plans", [])))


def test_group_page_aggregates_commercial_projects_only_after_page_selection(saved_db):  # noqa: F811
    manifest = seed_scale_corpus(saved_db)
    assert manifest["synthetic_fixture"] is True
    # The shared seeder inserts a precomputed generation before all direct
    # synthetic derived rows. Bind that fixture generation to the completed
    # input revision without rebuilding or collapsing its injected rows.
    with saved_db.begin() as session:
        generation = session.get(BrowseGeneration, UUID(manifest["generation_id"]))
        state = session.get(BrowseState, 1)
        assert generation is not None and state is not None
        generation.input_revision = state.input_revision
    engine = saved_db.kw["bind"]

    for canonical_only in (False, True):
        statements = []
        facet_statements = []

        def capture(
            _conn,
            _cursor,
            statement,
            parameters,
            _context,
            _executemany,
            _statements=statements,
            _facet_statements=facet_statements,
        ):
            normalized = " ".join(statement.lower().split())
            if "count(*) over() as total" in normalized and "from grouped g" in normalized:
                _statements.append((statement, dict(parameters)))
            if "array_agg" in normalized and "from all_rows b join assigned a" in normalized:
                _facet_statements.append((statement, dict(parameters)))

        event.listen(engine, "before_cursor_execute", capture)
        try:
            for page_limit in (1, 25, 50):
                statements.clear()
                facet_statements.clear()
                with saved_db() as session:
                    session.execute(text("SET TRANSACTION READ ONLY"))
                    result = groups(session, limit=page_limit, canonical_only=canonical_only)
                    assert len(statements) == 1
                    assert len(result["items"]) == page_limit

                    statement, parameters = statements[0]
                    normalized = " ".join(statement.lower().split())
                    page_cte = normalized.index("page_rows as materialized")
                    project_keys_cte = normalized.index("page_project_rows as materialized")
                    payload_cte = normalized.index("page_commercial_projects as")
                    assert page_cte < project_keys_cte < payload_cte
                    assert "jsonb_agg" not in normalized[:payload_cte]
                    project_key_sql = normalized[project_keys_cte:payload_cte]
                    assert "from page_rows p join assigned a" in project_key_sql
                    assert "from page_project_rows p join browse_rows b" in normalized[payload_cte:]
                    assert "customer_facts" in normalized[:page_cte]
                    assert "customer_developments" in normalized[:page_cte]
                    assert "ar.compact->'customer_facts'" not in normalized[:page_cte]
                    assert "ar.compact->'customer_developments'" not in normalized[:page_cte]
                    assert "b.compact->'customer_facts'" in normalized[payload_cte:]
                    assert "b.compact->'customer_developments'" in normalized[payload_cte:]
                    assert re.search(
                        r"join browse_rows b on b\.generation_id\s*=\s*[^ ]+\s+and "
                        r"b\.project_id\s*=\s*p\.project_id",
                        normalized[payload_cte:],
                    )
                    plan = (
                        session.connection()
                        .exec_driver_sql(
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, VERBOSE) " + statement,
                            parameters,
                        )
                        .scalar_one()[0]["Plan"]
                    )
                    page_row_scans = [
                        node
                        for node in _walk(plan)
                        if node.get("Node Type") == "CTE Scan"
                        and node.get("CTE Name") == "page_rows"
                    ]
                    payload_aggregates = [
                        node
                        for node in _walk(plan)
                        if node.get("Node Type") == "Aggregate"
                        and "jsonb_agg" in json.dumps(node.get("Output", [])).lower()
                    ]
                    assert page_row_scans
                    assert all(node["Actual Rows"] <= page_limit for node in page_row_scans)
                    project_key_scans = [
                        node
                        for node in _walk(plan)
                        if node.get("Node Type") == "CTE Scan"
                        and node.get("CTE Name") == "page_project_rows"
                    ]
                    assert project_key_scans
                    assert all(node["Actual Rows"] > 0 for node in project_key_scans)
                    assert len(payload_aggregates) == 1
                    assert payload_aggregates[0]["Actual Rows"] <= len(result["items"])
                    assert result["facets"]["regions"]
                    assert result["facets"]["stages"]

                    if canonical_only:
                        assert len(facet_statements) == 1
                        facet_statement, facet_parameters = facet_statements[0]
                        assert "jsonb_agg" not in facet_statement.lower()
                        facet_plan = (
                            session.connection()
                            .exec_driver_sql(
                                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, VERBOSE) "
                                + facet_statement,
                                facet_parameters,
                            )
                            .scalar_one()[0]["Plan"]
                        )
                        assert not any(
                            node.get("Node Type") == "Aggregate"
                            and "jsonb_agg" in json.dumps(node.get("Output", [])).lower()
                            for node in _walk(facet_plan)
                        )
                    else:
                        assert not facet_statements
        finally:
            event.remove(engine, "before_cursor_execute", capture)


def test_narrow_list_cte_preserves_full_page_projection(saved_db, monkeypatch):  # noqa: F811
    """The narrow cohort rows must publish the same selected-page facts and detail signal."""
    from uuid import UUID

    from rollup_scale_fixture import seed_scale_corpus

    manifest = seed_scale_corpus(saved_db)
    with saved_db.begin() as session:
        generation = session.get(BrowseGeneration, UUID(manifest["generation_id"]))
        state = session.get(BrowseState, 1)
        assert generation is not None and state is not None
        generation.input_revision = state.input_revision
        browse_row = (
            session.execute(
                text(
                    "SELECT need_id, compact FROM browse_rows "
                    "WHERE generation_id=:generation "
                    "ORDER BY rank_score DESC LIMIT 1"
                ),
                {"generation": generation.id},
            )
            .mappings()
            .one()
        )
        package = {
            "version": "customer-facts-v1",
            "project_id": str(browse_row["compact"]["project_id"]),
            "capacity_claims": [],
            "timeline_claims": [],
            "commissioning_inputs": [],
        }
        session.execute(
            text(
                "UPDATE browse_rows SET compact=compact || CAST(:compact AS jsonb) "
                "WHERE generation_id=:generation AND need_id=:need_id"
            ),
            {
                "compact": json.dumps(
                    {
                        "customer_facts": [package],
                        "customer_priority": {"score": 81, "confidence": 70},
                        "customer_developments": [
                            {
                                "id": "fixture-development",
                                "summary": "Synthetic update",
                                "source_date": "2026-11-12",
                                "observed_at": "2026-11-13T00:00:00+00:00",
                            }
                        ],
                    }
                ),
                "generation": generation.id,
                "need_id": browse_row["need_id"],
            },
        )

    with saved_db() as session:
        narrow = groups(session, limit=1, canonical_only=True)

    original_ctes = customer_results._ctes

    def full_width_ctes(where, shortlist_data=None, *, include_commercial_projects=True):
        # Reference path retains the original full compact payload inside the
        # whole-cohort CTE and computes commercial_projects before pagination.
        return original_ctes(where, shortlist_data, include_commercial_projects=True)

    monkeypatch.setattr(customer_results, "_ctes", full_width_ctes)
    with saved_db() as session:
        reference = groups(session, limit=1, canonical_only=True)

    def stable(value):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items() if key != "as_of"}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    assert stable(narrow) == stable(reference)
    card = narrow["items"][0]["commercial_intelligence"]
    assert card["details_available"] is True
    assert card["recent_developments"][0]["source_date"] == "2026-11-12"


def test_hydration_keeps_every_selected_account_project_and_need(saved_db):  # noqa: F811
    """A page account's 30 sibling projects hydrate despite a one-group page."""
    manifest = seed_scale_corpus(saved_db)
    generation_id = UUID(manifest["generation_id"])
    with saved_db.begin() as session:
        generation = session.get(BrowseGeneration, generation_id)
        state = session.get(BrowseState, 1)
        assert generation is not None and state is not None
        generation.input_revision = state.input_revision
        identity = CompanyIdentity(id=UUID("00000000-0000-0000-0000-000000000123"))
        session.add(identity)
        session.flush()
        selected = (
            session.query(BrowseRow)
            .filter(
                BrowseRow.generation_id == generation_id,
                BrowseRow.compact["project_metadata"]["sector"].astext == "other",
            )
            .order_by(BrowseRow.project_id)
            .limit(30)
            .all()
        )
        assert len(selected) == 30
        session.add_all(
            [
                BrowseCustomerMembership(
                    generation_id=generation_id,
                    company_identity_id=identity.id,
                    project_id=row.project_id,
                    organization_name="Synthetic 30 project account",
                    role="owner_developer",
                )
                for row in selected
            ]
        )
        for row in selected:
            need_marker = str(row.need_id)
            compact = dict(row.compact)
            compact.update(
                {
                    "customer_priority": {"score": 99, "confidence": 95},
                    "customer_facts": [
                        {
                            "version": "customer-facts-v1",
                            "project_id": str(row.project_id),
                            "synthetic_need_marker": need_marker,
                            "capacity_claims": [],
                            "timeline_claims": [],
                            "commissioning_inputs": [],
                        }
                    ],
                }
            )
            row.compact = compact
        expected = {str(row.project_id): str(row.need_id) for row in selected}

    statements = []
    engine = saved_db.kw["bind"]

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if "page_rows as materialized" in normalized and "from grouped g" in normalized:
            statements.append((statement, dict(parameters)))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with saved_db() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            page = groups(
                session,
                limit=1,
                canonical_only=False,
                search="Synthetic 30 project account",
            )
            assert len(page["items"]) == 1
            assert page["items"][0]["name"] == "Synthetic 30 project account"
            assert len(statements) == 1
            query, parameters = statements[0]
            raw = session.connection().exec_driver_sql(query, parameters).mappings().one()
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    hydrated = {
        project["project_id"]: project["facts"][0]["synthetic_need_marker"]
        for project in raw["commercial_projects"]
    }
    assert hydrated == expected
