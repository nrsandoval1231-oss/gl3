"""Page scope the customer-project JSON payload without changing page semantics."""

import json
from uuid import UUID

from rollup_scale_fixture import seed_scale_corpus
from sqlalchemy import event, text
from test_saved_browse import saved_db  # noqa: F401,F811

from gridlens.intelligence.customer_results import groups
from gridlens.persistence.models import BrowseGeneration, BrowseState

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
            with saved_db() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                result = groups(session, limit=25, canonical_only=canonical_only)
                assert len(statements) == 1
                assert len(result["items"]) == 25

                statement, parameters = statements[0]
                normalized = " ".join(statement.lower().split())
                page_cte = normalized.index("page_rows as materialized")
                payload_cte = normalized.index("page_commercial_projects as")
                assert page_cte < payload_cte
                assert "jsonb_agg" not in normalized[:payload_cte]
                assert "from page_rows p join assigned a" in normalized[payload_cte:]
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
                    if node.get("Node Type") == "CTE Scan" and node.get("CTE Name") == "page_rows"
                ]
                payload_aggregates = [
                    node
                    for node in _walk(plan)
                    if node.get("Node Type") == "Aggregate"
                    and "jsonb_agg" in json.dumps(node.get("Output", [])).lower()
                ]
                assert page_row_scans
                assert all(node["Actual Rows"] <= 25 for node in page_row_scans)
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
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, VERBOSE) " + facet_statement,
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
