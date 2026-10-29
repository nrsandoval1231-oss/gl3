"""Keep common operator/customer pages to one cohort aggregate query."""

from sqlalchemy import event, text
from test_saved_browse import rebuild, saved_db, seed  # noqa: F401,F811

from gridlens.intelligence.customer_results import group_projects, groups


def _captured_statements(engine, call):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return result, statements


def test_group_page_counts_share_the_cohort_aggregate(saved_db):  # noqa: F811
    seed(saved_db, count=8, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    engine = saved_db.kw["bind"]

    with saved_db() as session:
        first, statements = _captured_statements(
            engine, lambda: groups(session, sector="all", limit=1)
        )
        cohort_queries = [statement for statement in statements if "from grouped" in statement]
        assert len(cohort_queries) == 1
        assert "count(*) over() as total" in cohort_queries[0]
        assert first["total"] > 1

        next_page = groups(
            session,
            sector="all",
            limit=1,
            offset=1,
            token=first["cohort_token"],
        )
        assert next_page["total"] == first["total"]
        assert next_page["items"][0]["id"] != first["items"][0]["id"]

        children, child_statements = _captured_statements(
            engine,
            lambda: group_projects(
                session,
                first["items"][0]["id"],
                sector="all",
                limit=1,
                parent_token=first["cohort_token"],
            ),
        )
        child_queries = [
            statement for statement in child_statements if "from assigned a" in statement
        ]
        assert len(child_queries) == 1
        assert "count(*) over() as total" in child_queries[0]
        assert children["total"] == 1
        assert len(children["items"]) == 1

        out_of_range = group_projects(
            session,
            first["items"][0]["id"],
            sector="all",
            limit=1,
            offset=5,
            token=children["cohort_token"],
            parent_token=first["cohort_token"],
        )
        assert out_of_range["items"] == []
        assert out_of_range["total"] == children["total"]

        default_jit = session.scalar(text("SHOW jit"))
        groups(session, search="Synthetic 1", sector="all")
        assert session.scalar(text("SHOW jit")) == "off"
        session.commit()
        assert session.scalar(text("SHOW jit")) == default_jit
