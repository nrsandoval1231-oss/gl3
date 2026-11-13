"""Transaction and candidate-set preservation for the PR197 query reconciliation."""

from sqlalchemy.orm import Session

from gridlens.api.app import _begin_consistent_read

pytest_plugins = ["test_saved_browse"]


def test_consistent_read_disables_jit_only_inside_its_repeatable_read_transaction(saved_db):
    with saved_db.kw["bind"].connect() as connection:
        original = connection.exec_driver_sql("SHOW jit").scalar_one()
        connection.exec_driver_sql("SET jit = on")
        connection.commit()
        try:
            with Session(bind=connection) as session:
                _begin_consistent_read(session)
                assert session.connection().exec_driver_sql("SHOW jit").scalar_one() == "off"
                assert (
                    session.connection().exec_driver_sql("SHOW transaction_isolation").scalar_one()
                    == "repeatable read"
                )
                session.rollback()
                assert connection.exec_driver_sql("SHOW jit").scalar_one() == "on"
                connection.rollback()
        finally:
            # The test must also preserve environments whose default is already off.
            assert original in {"on", "off"}
            connection.exec_driver_sql(f"SET jit = {original}")
            connection.commit()


def test_materialized_contact_candidates_preserve_method_and_named_professional_payloads(
    saved_db, monkeypatch
):
    """Selection equivalence; native publication authority is an explicit fixture seam.

    The separate real native source/suppression journey remains required. This
    test compares the actual previous correlated SQL with its reconciled query
    against the same persisted candidates and the same publication/ranking guard.
    """
    from copy import deepcopy
    from uuid import uuid4

    from sqlalchemy import event, select
    from test_saved_browse import seed

    from gridlens.intelligence import project_contact_actions
    from gridlens.intelligence.customer_results import groups
    from gridlens.intelligence.saved_browse import current_generation, rebuild
    from gridlens.persistence.models import (
        BrowseCustomerMembership,
        BrowseRow,
        CompanyIdentity,
    )

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        company = CompanyIdentity(id=uuid4())
        session.add(company)
        session.flush()
        company_id = str(company.id)
        rows = session.scalars(select(BrowseRow).order_by(BrowseRow.project_id)).all()
        for index, row in enumerate(rows):
            common = {
                "company_identity_id": company_id,
                "company": "Account",
                "project_id": str(row.project_id),
                "name": "Casey Example",
                "title": "Commissioning Director",
                "person_identity_id": str(uuid4()),
                "source_url": "https://example.test/native",
            }
            row.compact = {
                **row.compact,
                "project_metadata": {"sector": "data_centers"},
                "contact_actions": [
                    {
                        **common,
                        "kind": "email",
                        "href": "mailto:casey@example.test",
                        "responsibility": "General company contact path",
                    }
                ]
                if index
                else [],
                "contact_people": [
                    {
                        **common,
                        "record_type": "contact_person",
                        "responsibility": "Verified project responsibility",
                    }
                ]
                if not index
                else [],
            }
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=company.id,
                    project_id=row.project_id,
                    organization_name="Account",
                    role="owner_developer",
                )
            )
    guarded = []

    def authorized(_session, records):
        guarded.extend(deepcopy(records))
        return [record for record in records if record.get("company_identity_id") == company_id]

    monkeypatch.setattr(project_contact_actions, "filter_project_contact_records", authorized)
    use_reference = [True]
    candidate_queries = []

    def previous_sql(_connection, _cursor, statement, parameters, _context, _many):
        if "contact_assigned AS MATERIALIZED" in statement:
            candidate_queries.append(use_reference[0])
            if use_reference[0]:
                start = statement.index(", contact_assigned AS MATERIALIZED")
                end = statement.index("SELECT a.group_key", start)
                statement = statement[:start] + statement[end:]
                statement = statement.replace("FROM contact_assigned a", "FROM assigned a")
                start = statement.index("JOIN (SELECT asset_key,")
                end = statement.index("JOIN browse_rows b", start)
                statement = statement[:start] + statement[end:]
                statement = statement.replace(
                    "ap.project_ids AS asset_project_ids",
                    "ARRAY(SELECT ar2.project_id FROM all_rows ar2 "
                    "WHERE ar2.asset_key=a.asset_key GROUP BY ar2.project_id "
                    "ORDER BY ar2.project_id) AS asset_project_ids",
                )
        return statement, parameters

    engine = saved_db.kw["bind"]
    event.listen(engine, "before_cursor_execute", previous_sql, retval=True)
    try:
        with saved_db() as session:
            _begin_consistent_read(session)
            before = groups(session)
        use_reference[0] = False
        with saved_db() as session:
            _begin_consistent_read(session)
            after = groups(session)
    finally:
        event.remove(engine, "before_cursor_execute", previous_sql)

    def stable(value):
        if isinstance(value, list):
            return [stable(item) for item in value]
        if isinstance(value, dict):
            result = {key: stable(item) for key, item in value.items()}
            if isinstance(result.get("freshness"), dict):
                result["freshness"].pop("as_of", None)
            return result
        return value

    assert candidate_queries == [True, False]
    assert stable(before) == stable(after)
    project = after["items"][0]["account_contact_project"]
    assert project and project["contact_people"][0]["name"] == "Casey Example"
    assert any(record.get("kind") == "email" for record in guarded)
    assert any(record.get("record_type") == "contact_person" for record in guarded)
