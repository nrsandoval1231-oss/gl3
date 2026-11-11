"""Statement-level, index-driven browse dirty-project invalidation (schema 0056).

The row-level trigger set and the single-OR ``browse_observation_projects`` that preceded
migration 0056 are kept below as ``OLD_DIRTY_SQL``, the oracle the new implementation is held to:
the same project-id sets, the same revisions and the same stale-since behaviour.
"""

import importlib.util
import json
import random
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from gridlens.persistence import (
    browse_invalidation as bi,
)
from gridlens.persistence import (
    models as _models,  # noqa: F401  # registers all tables on Base.metadata
)
from gridlens.persistence.database import Base
from gridlens.settings import settings

# Verbatim copy of the dirty_browse_project / browse_observation_projects definitions installed by
# migrations 0030-0054 (row-level triggers, one function call per row).
OLD_DIRTY_SQL = """
    CREATE OR REPLACE FUNCTION browse_observation_projects(
        oid uuid, eid uuid, source_key text, external_key text
    ) RETURNS TABLE(project_id uuid) LANGUAGE sql STABLE AS $$
        SELECT n.project_id FROM need_observations l
            JOIN power_needs n ON n.id = l.need_id WHERE l.observation_id = oid
        UNION
        SELECT p.id FROM projects p WHERE
            (p.source_id = source_key AND p.external_id = external_key)
            OR EXISTS (SELECT 1 FROM observations o WHERE o.id = oid
                AND o.source_id = p.source_id AND o.external_id = p.external_id)
        UNION
        SELECT l.project_id FROM lifecycle_events l WHERE l.observation_id = oid
            OR l.evidence_id = eid OR l.evidence_id IN
                (SELECT e.id FROM evidence e WHERE e.observation_id = oid)
        UNION
        SELECT b.project_id FROM buying_chain_evidence b
            WHERE b.retained_evidence_id = eid OR b.retained_evidence_id IN
                (SELECT e.id FROM evidence e WHERE e.observation_id = oid)
        UNION
        SELECT f.project_id FROM interconnection_fact_versions f
            WHERE f.evidence_id = eid OR f.evidence_id IN
                (SELECT e.id FROM evidence e WHERE e.observation_id = oid)
        UNION
        SELECT m.candidate_project_id FROM project_match_decisions m
            WHERE m.observation_id = oid AND m.candidate_project_id IS NOT NULL
    $$;
    CREATE OR REPLACE FUNCTION dirty_browse_project() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE payload jsonb; pid uuid; next_revision bigint; oid uuid; eid uuid;
    BEGIN
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        -- Acquire the writer/publication fence BEFORE scanning dependencies.
        -- Separate statements see dependencies committed while waiting on it.
        SELECT input_revision + 1 INTO next_revision FROM browse_state WHERE id = 1 FOR UPDATE;
        FOR payload IN SELECT value FROM jsonb_array_elements(
            CASE WHEN TG_OP = 'INSERT' THEN jsonb_build_array(to_jsonb(NEW))
                 WHEN TG_OP = 'DELETE' THEN jsonb_build_array(to_jsonb(OLD))
                 ELSE jsonb_build_array(to_jsonb(OLD), to_jsonb(NEW)) END)
        LOOP
            pid := NULL; oid := NULL; eid := NULL;
            IF TG_TABLE_NAME = 'projects' THEN
                pid := (payload->>'id')::uuid;
            ELSIF TG_TABLE_NAME IN (
                'power_needs', 'project_lifecycles', 'lifecycle_events',
                'project_material_states', 'buying_chain_evidence',
                'buying_chain_claims', 'buying_chain_runs', 'interconnection_fact_versions'
            ) THEN
                pid := (payload->>'project_id')::uuid;
            ELSIF TG_TABLE_NAME IN (
                'call_fact_versions', 'call_fact_decisions', 'need_workflow_status_events',
                'need_observations', 'power_need_briefs', 'power_need_brief_versions'
            ) THEN
                SELECT project_id INTO pid FROM power_needs WHERE id = (payload->>'need_id')::uuid;
                IF pid IS NULL THEN
                    UPDATE browse_state SET full_revision = next_revision WHERE id = 1;
                END IF;
            ELSIF TG_TABLE_NAME = 'observations' THEN
                oid := (payload->>'id')::uuid;
            ELSIF TG_TABLE_NAME = 'pursuit_documents' THEN
                IF NOT scope_browse_pursuit(
                    (SELECT to_jsonb(p) FROM pursuits p
                     WHERE p.id = (payload->>'pursuit_id')::uuid), next_revision
                ) THEN
                    UPDATE browse_state SET full_revision = next_revision WHERE id = 1;
                END IF;
            ELSIF TG_TABLE_NAME IN ('evidence', 'interpretations', 'signal_decisions',
                                   'change_events', 'project_match_decisions') THEN
                oid := (payload->>'observation_id')::uuid;
                IF TG_TABLE_NAME = 'evidence' THEN eid := (payload->>'id')::uuid; END IF;
                pid := COALESCE(payload->>'project_id', payload->>'candidate_project_id')::uuid;
            ELSE
                UPDATE browse_state SET full_revision = next_revision WHERE id = 1;
            END IF;
            IF pid IS NOT NULL THEN
                INSERT INTO browse_dirty_projects(project_id, revision) VALUES(pid, next_revision)
                ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
            END IF;
            IF oid IS NOT NULL THEN
                INSERT INTO browse_dirty_projects(project_id, revision)
                SELECT affected.project_id, next_revision FROM browse_observation_projects(
                    oid, eid, payload->>'source_id', payload->>'external_id'
                ) affected WHERE affected.project_id IS NOT NULL
                ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
                -- A known unlinked observation has no browse consumer yet. Its
                -- later link/direct project insertion will invalidate that owner.
            END IF;
        END LOOP;
        RETURN NULL;
    END $$
"""


def old_row_trigger_operations(table):
    if table in bi.DIRTY_NO_INSERT_TABLES:
        return "UPDATE OR DELETE"
    return "INSERT OR UPDATE OR DELETE"


def install_old(connection):
    """Replace the statement-level dirty triggers with the pre-0056 row-level ones."""
    for table in bi.SCOPED_TABLES:
        for name, _operation, _transition in bi.DIRTY_TRIGGER_OPERATIONS:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS dirty_browse_{name} ON {table}")
    connection.exec_driver_sql(OLD_DIRTY_SQL)
    for table in bi.SCOPED_TABLES:
        connection.exec_driver_sql(f"""
            CREATE TRIGGER dirty_browse AFTER {old_row_trigger_operations(table)} ON {table}
            FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
        """)


def require_database():
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL trigger tests")
    database = make_url(settings.test_database_url).database
    assert database and database.endswith("_test") and "corpus" not in database.lower(), (
        "An explicit disposable *_test database is required"
    )


@pytest.fixture
def schemas():
    require_database()
    admin = create_engine(settings.test_database_url)
    created = {}
    for label in ("old", "new"):
        schema = f"s56_{label}_" + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(
            settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
        )
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            bi.install(connection)
            if label == "old":
                install_old(connection)
        created[label] = (schema, engine)
    yield {label: engine for label, (_schema, engine) in created.items()}
    for schema, engine in created.values():
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


def u(name):
    return str(uuid5(NAMESPACE_URL, f"gl3:s56:{name}"))


SOURCE = (
    "INSERT INTO sources (id, publisher, endpoint, family, geography, industries,"
    " retrieval_method, cadence_hours, enabled, health) VALUES "
    "('src-a', 'A', 'https://a.test', 'f', 'TX', '[]', 'fixture', 24, false, '{}'),"
    "('src-b', 'B', 'https://b.test', 'f', 'TX', '[]', 'fixture', 24, false, '{}')"
)


def project(name, source, external):
    return f"('{u(name)}', 'key-{name}', 'Project {name}', '{source}', '{external}', '{{}}')"


def observation(name, source, external):
    return (
        f"('{u(name)}', '{source}', '{external}', 'Observation {name}',"
        f" 'https://obs.test/{name}', 'h-{name}')"
    )


def evidence(name, obs, content_hash=None):
    return (
        f"('{u(name)}', '{u(obs)}', 'Evidence {name}', 'https://ev.test/{name}', 'loc',"
        f" '{content_hash or 'h-' + name}')"
    )


def seed_statements():
    yield SOURCE
    yield (
        "INSERT INTO projects (id, identity_key, name, source_id, external_id, identity_facts)"
        " VALUES "
        + ", ".join(
            [
                project("P1", "src-a", "x1"),
                project("P2", "src-a", "x2"),
                project("P3", "src-b", "x3"),
                project("P4", "src-b", "x4"),
                project("P5", "src-a", "x5"),
                project("P6", "src-b", "x7"),
            ]
        )
    )
    yield (
        "INSERT INTO power_needs (id, project_id, activity_key, tier, rationale, supply) VALUES "
        + ", ".join(
            f"('{u(n)}', '{u(p)}', 'construction', 'Signal', 'r', 'Unknown')"
            for n, p in (("N1", "P1"), ("N2", "P2"), ("N3", "P3"))
        )
    )
    yield (
        "INSERT INTO observations (id, source_id, external_id, title, url, content_hash) VALUES "
        + ", ".join(
            [
                observation("O1", "src-a", "x1"),
                observation("O2", "src-a", "x2"),
                observation("O3", "src-b", "x3"),
                observation("O4", "src-b", "orphan"),
                observation("O5", "src-a", "x5"),
                observation("O6", "src-b", "x4"),
            ]
        )
    )
    yield (
        "INSERT INTO evidence (id, observation_id, title, url, extraction_location, content_hash)"
        " VALUES " + ", ".join(evidence(f"E{i}", f"O{i}") for i in range(1, 7))
    )
    yield (
        "INSERT INTO need_observations (need_id, observation_id) VALUES "
        f"('{u('N1')}', '{u('O3')}'), ('{u('N2')}', '{u('O2')}'), ('{u('N3')}', '{u('O1')}')"
    )
    yield (
        "INSERT INTO lifecycle_events (id, project_id, observation_id, evidence_id, state,"
        " event_type, value_kind) VALUES "
        f"('{u('LE1')}', '{u('P1')}', '{u('O1')}', '{u('E1')}', 's', 'a', 'k'),"
        f"('{u('LE2')}', '{u('P2')}', '{u('O3')}', '{u('E3')}', 's', 'b', 'k'),"
        f"('{u('LE3')}', '{u('P4')}', '{u('O6')}', '{u('E4')}', 's', 'c', 'k')"
    )
    yield (
        "INSERT INTO buying_chain_evidence (id, project_id, url, title, excerpt, content_hash,"
        " extraction_location, observed_at, last_seen_at, project_match_reason,"
        " retained_evidence_id) VALUES "
        f"('{u('BE1')}', '{u('P2')}', 'https://b/1', 't', 'e', 'bh1', 'l', now(), now(), 'r',"
        f" '{u('E5')}'),"
        f"('{u('BE2')}', '{u('P4')}', 'https://b/2', 't', 'e', 'bh2', 'l', now(), now(), 'r',"
        f" '{u('E4')}')"
    )
    yield (
        "INSERT INTO interconnection_fact_versions (id, project_id, evidence_id, payload) VALUES "
        f"('{u('IF1')}', '{u('P3')}', '{u('E6')}', '{{}}'),"
        f"('{u('IF2')}', '{u('P1')}', '{u('E2')}', '{{}}')"
    )
    yield (
        "INSERT INTO project_match_decisions (observation_id, candidate_project_id, evidence_id,"
        " matched_facts, identity_facts, reason, decision) VALUES "
        f"('{u('O4')}', '{u('P5')}', '{u('E4')}', '{{}}', '{{}}', 'r', 'candidate'),"
        f"('{u('O4')}', NULL, '{u('E4')}', '{{}}', '{{}}', 'r', 'new'),"
        f"('{u('O6')}', '{u('P1')}', '{u('E6')}', '{{}}', '{{}}', 'r', 'candidate')"
    )
    yield (
        "INSERT INTO interpretations (observation_id, content_hash) VALUES "
        f"('{u('O1')}', 'i1'), ('{u('O3')}', 'i3')"
    )
    yield (
        "INSERT INTO signal_decisions (observation_id, content_hash, policy_version, decision,"
        " source, dimensions, reason) VALUES "
        f"('{u('O2')}', 's2', 'p', 'd', 'fixture', '{{}}', 'r'),"
        f"('{u('O4')}', 's4', 'p', 'd', 'fixture', '{{}}', 'r')"
    )
    yield (
        "INSERT INTO change_events (observation_id, content_hash, kind, project_id) VALUES "
        f"('{u('O1')}', 'c1', 'k', '{u('P2')}'), ('{u('O4')}', 'c4', 'k', NULL)"
    )
    yield (
        "INSERT INTO project_lifecycles (project_id, current_state, open_questions,"
        " monitoring_requirements) VALUES "
        f"('{u('P1')}', 's', '[]', '[]'), ('{u('P2')}', 's', '[]', '[]')"
    )
    yield (
        "INSERT INTO project_material_states (project_id, state, revision)"
        f" VALUES ('{u('P3')}', '{{}}', 1)"
    )
    yield (
        "INSERT INTO call_fact_versions (id, need_id, project_id, client_id, activity_key,"
        " facility_scope, fact_type, value, reporter_name, confirmation_channel, confirmed_at,"
        " effective_from, content_hash, recorded_by) VALUES "
        f"('{u('CFV1')}', '{u('N1')}', '{u('P1')}', '{u('CL1')}', 'a', 's', 't', '{{}}', 'r',"
        " 'c', now(), now(), 'h', 'tester')"
    )
    yield (
        "INSERT INTO call_fact_decisions (id, need_id, fact_version_id, version, client_id,"
        " decision, expected_version, reason, content_hash, actor) VALUES "
        f"('{u('CFD1')}', '{u('N2')}', '{u('CFV1')}', 1, '{u('CL2')}', 'confirmed', 0, 'r', 'h',"
        " 'tester')"
    )
    yield (
        "INSERT INTO need_workflow_status_events (id, need_id, project_id, version, client_id,"
        " status, expected_version, reason, content_hash, actor) VALUES "
        f"('{u('NW1')}', '{u('N3')}', '{u('P3')}', 1, '{u('CL3')}', 'open', 0, 'r', 'h',"
        " 'tester')"
    )
    yield (
        "INSERT INTO power_need_briefs (need_id, policy_version, schema_version, model, status,"
        " citations, input_tokens, output_tokens) VALUES "
        f"('{u('N1')}', 'p', 's', 'm', 'ok', '[]', 1, 1)"
    )
    yield (
        "INSERT INTO power_need_brief_versions (id, need_id, input_fingerprint, policy_version,"
        " schema_version, model, result, citations, generated_at, input_tokens, output_tokens)"
        f" VALUES ('{u('PB1')}', '{u('N2')}', 'f', 'p', 's', 'm', '{{}}', '[]', now(), 1, 1)"
    )
    yield (
        "INSERT INTO buying_chain_claims (id, project_id, entity_key, fingerprint, policy_version,"
        " organization, category, organization_relationship, person_organization_relationship,"
        " person_project_relationship, evidence_strength, reason, citations, public_contacts,"
        " observed_at) VALUES "
        f"('{u('BC1')}', '{u('P2')}', 'e', 'f', 'p', 'Org', 'c', 'r', 'r', 'r', 's', 'r', '[]',"
        " '[]', now())"
    )
    yield (
        "INSERT INTO buying_chain_runs (id, project_id, input_hash, evidence_ids, claim_ids,"
        " policy_version, status, documents_checked, candidates_added, unresolved) VALUES "
        f"('{u('BR1')}', '{u('P3')}', 'h', '[]', '[]', 'p', 'ok', 0, 0, '[]')"
    )
    yield (
        "INSERT INTO pursuits (id, identity_key, project_id, project_ids, snapshot,"
        " research_status, research_errors) VALUES "
        f"('{u('PA')}', 'auto:a', '{u('P1')}', '[\"{u('P1')}\", \"{u('P2')}\"]', '{{}}', 'done',"
        " '[]'),"
        f"('{u('PB')}', 'auto:b', '{u('P2')}', '{{}}', '{{}}', 'done', '[]'),"
        f"('{u('PC')}', 'commercial-need:{u('N2')}', '{u('P2')}', '[\"{u('P2')}\"]', '{{}}',"
        " 'done', '[]')"
    )
    yield (
        "INSERT INTO pursuit_documents (id, pursuit_id, url, content_hash, source) VALUES "
        f"('{u('PD1')}', '{u('PA')}', 'https://d/1', 'd1', '{{}}'),"
        f"('{u('PD2')}', '{u('PB')}', 'https://d/2', 'd2', '{{}}'),"
        f"('{u('PD3')}', '{u('PC')}', 'https://d/3', 'd3', '{{}}')"
    )
    yield (
        "INSERT INTO browse_generations (id, input_revision, policy_version, built_at,"
        " valid_until, row_count, digest, counts) VALUES "
        f"('{u('GEN')}', 0, 'p', now(), now() + interval '1 day', 0, 'd', '{{}}')"
    )


def reset_state(connection, label):
    """A known current state: no dirty rows, a published generation equal to the revision."""
    connection.exec_driver_sql("DELETE FROM browse_dirty_projects")
    gen = u("GEN-" + label)
    connection.exec_driver_sql(
        "INSERT INTO browse_generations (id, input_revision, policy_version, built_at,"
        " valid_until, row_count, digest, counts) SELECT "
        f"'{gen}', input_revision, 'p', now(), now() + interval '1 day', 0, 'd', '{{}}'"
        " FROM browse_state WHERE id = 1 ON CONFLICT (id) DO UPDATE SET"
        " input_revision = EXCLUDED.input_revision"
    )
    connection.exec_driver_sql(
        f"UPDATE browse_state SET generation_id = '{gen}', prepared_generation_id = NULL"
        " WHERE id = 1"
    )


def snapshot(connection):
    state = connection.exec_driver_sql(
        "SELECT input_revision, full_revision, structural_revision, stale_since IS NOT NULL,"
        " prepared_generation_id IS NULL FROM browse_state WHERE id = 1"
    ).one()
    dirty = connection.exec_driver_sql(
        "SELECT project_id::text, revision FROM browse_dirty_projects ORDER BY 1"
    ).all()
    return {
        "input": state[0],
        "full": state[1],
        "structural": state[2],
        "stale": state[3],
        "unprepared": state[4],
        "dirty": [list(row) for row in dirty],
    }


def dependents(table, where):
    """Statements removing rows that reference ``where`` rows of ``table``, leaves first."""
    statements = []
    for child in Base.metadata.tables.values():
        for fk in child.foreign_keys:
            if fk.column.table.name != table.name or child.name == table.name:
                continue
            parent_col, child_col = fk.column.name, fk.parent.name
            inner = f"{child_col} IN (SELECT {parent_col} FROM {table.name} WHERE {where})"
            statements.extend(dependents(child, inner))
            statements.append(f"DELETE FROM {child.name} WHERE {inner}")
    return statements


ONE = "ctid = (SELECT ctid FROM {t} ORDER BY {t}::text LIMIT 1)"


def first_column(table):
    return next(iter(Base.metadata.tables[table].columns)).name


def targeted_steps():
    """(name, statements) over key-changing updates, multi-row inserts and cascades."""
    yield (
        "power_needs-move",
        [f"UPDATE power_needs SET project_id = '{u('P3')}' WHERE id = '{u('N1')}'"],
    )
    yield (
        "lifecycle-move",
        [f"UPDATE lifecycle_events SET project_id = '{u('P4')}' WHERE id = '{u('LE1')}'"],
    )
    yield (
        "need_observation-move",
        [f"UPDATE need_observations SET need_id = '{u('N3')}' WHERE need_id = '{u('N1')}'"],
    )
    yield (
        "observation-rekey",
        [f"UPDATE observations SET source_id = 'src-b', external_id = 'x7' WHERE id = '{u('O4')}'"],
    )
    yield "observation-rekey-all", ["UPDATE observations SET external_id = external_id || 'z'"]
    yield (
        "evidence-reparent",
        [f"UPDATE evidence SET observation_id = '{u('O4')}' WHERE id = '{u('E1')}'"],
    )
    yield (
        "match-candidate-move",
        [
            f"UPDATE project_match_decisions SET candidate_project_id = '{u('P3')}'"
            f" WHERE observation_id = '{u('O4')}' AND candidate_project_id = '{u('P5')}'"
        ],
    )
    yield (
        "pursuit_document-move",
        [f"UPDATE pursuit_documents SET pursuit_id = '{u('PB')}' WHERE id = '{u('PD1')}'"],
    )
    yield (
        "buying_chain_evidence-move",
        [
            f"UPDATE buying_chain_evidence SET project_id = '{u('P3')}',"
            f" retained_evidence_id = '{u('E2')}' WHERE id = '{u('BE1')}'"
        ],
    )
    yield (
        "project-rekey",
        [
            f"UPDATE projects SET external_id = 'x1b' WHERE id = '{u('P1')}'",
            "UPDATE projects SET external_id = external_id || 'q'",
        ],
    )
    yield (
        "multi-row-observation-insert",
        [
            "INSERT INTO observations (id, source_id, external_id, title, url, content_hash)"
            " VALUES "
            + ", ".join(
                [
                    observation("O7", "src-a", "x1"),
                    observation("O8", "src-b", "x3"),
                    observation("O9", "src-b", "nothing"),
                ]
            ),
            "INSERT INTO evidence (id, observation_id, title, url, extraction_location,"
            " content_hash) VALUES "
            + ", ".join([evidence("E7", "O7"), evidence("E8", "O8"), evidence("E9", "O9")]),
        ],
    )
    yield (
        "multi-row-project-insert",
        [
            "INSERT INTO projects (id, identity_key, name, source_id, external_id, identity_facts)"
            " VALUES " + ", ".join([project("P7", "src-a", "n7"), project("P8", "src-a", "n8")]),
            "INSERT INTO power_needs (id, project_id, activity_key, tier, rationale, supply)"
            f" VALUES ('{u('N7')}', '{u('P7')}', 'a', 'Signal', 'r', 'Unknown'),"
            f"('{u('N8')}', '{u('P8')}', 'a', 'Signal', 'r', 'Unknown')",
        ],
    )
    yield (
        "need_observation-insert-both-ways",
        [
            "INSERT INTO need_observations (need_id, observation_id) VALUES "
            f"('{u('N1')}', '{u('O1')}'), ('{u('N2')}', '{u('O5')}')"
        ],
    )
    yield (
        "single-then-multi-statement-transaction",
        [
            f"UPDATE power_needs SET rationale = 'again' WHERE id = '{u('N1')}'",
            "UPDATE power_needs SET rationale = 'again2'",
            f"DELETE FROM project_lifecycles WHERE project_id = '{u('P1')}'",
        ],
    )
    yield (
        "pursuit-document-insert-unresolvable",
        [
            "INSERT INTO pursuit_documents (id, pursuit_id, url, content_hash, source) VALUES "
            f"('{u('PD9')}', '{u('PB')}', 'https://d/9', 'd9', '{{}}')"
        ],
    )
    for table in ("need_observations", "observations", "evidence", "projects", "power_needs"):
        # Dependents are removed under the replica role by run_battery, then the parent
        # row(s) are deleted with triggers enabled.
        yield f"cascade-delete-{table}", [f"DELETE FROM {table}"]


def generic_steps(connection):
    """Per scoped table: zero-row, no-op update (all, one), insert (all, one), delete (all, one),
    and TRUNCATE ... CASCADE. Each runs in its own rolled-back savepoint."""
    for table in bi.SCOPED_TABLES:
        column = first_column(table)
        yield f"{table}:zero-delete", [f"DELETE FROM {table} WHERE false"], None
        yield f"{table}:zero-update", [f"UPDATE {table} SET {column} = {column} WHERE false"], None
        yield (
            f"{table}:zero-insert",
            [f"INSERT INTO {table} SELECT * FROM {table} WHERE false"],
            None,
        )
        yield f"{table}:update-all", [f"UPDATE {table} SET {column} = {column}"], None
        yield (
            f"{table}:update-one",
            [f"UPDATE {table} SET {column} = {column} WHERE {ONE.format(t=table)}"],
            None,
        )
        yield f"{table}:truncate", [f"TRUNCATE {table} CASCADE"], None
        for label, where in (("all", "true"), ("one", ONE.format(t=table))):
            yield (
                f"{table}:delete-{label}",
                [f"DELETE FROM {table} WHERE {where}"],
                ("remove-dependents", table, where),
            )
            yield (
                f"{table}:insert-{label}",
                [
                    f"INSERT INTO {table} SELECT * FROM stash_{table}"
                    + ("" if label == "all" else f" ORDER BY stash_{table}::text LIMIT 1")
                ],
                ("stash-then-remove", table, "true"),
            )


def run_step(connection, name, statements, prepare, label):
    connection.exec_driver_sql("SAVEPOINT step")
    try:
        if prepare:
            kind, table, where = prepare
            if kind == "remove-dependents":
                table_obj = Base.metadata.tables[table]
                connection.exec_driver_sql("SET LOCAL session_replication_role = replica")
                for statement in dependents(table_obj, where):
                    connection.exec_driver_sql(statement)
                connection.exec_driver_sql("SET LOCAL session_replication_role = origin")
            else:  # stash the rows, then remove them without firing any trigger
                connection.exec_driver_sql("SET LOCAL session_replication_role = replica")
                connection.exec_driver_sql(
                    f"CREATE TEMP TABLE stash_{table} ON COMMIT DROP AS SELECT * FROM {table}"
                )
                connection.exec_driver_sql(f"DELETE FROM {table}")
                connection.exec_driver_sql("SET LOCAL session_replication_role = origin")
        reset_state(connection, label)
        outcome = {}
        try:
            connection.exec_driver_sql("SAVEPOINT statements")
            for statement in statements:
                connection.exec_driver_sql(statement)
            outcome = snapshot(connection)
        except DBAPIError as error:
            connection.exec_driver_sql("ROLLBACK TO SAVEPOINT statements")
            outcome = {"error": type(error.orig).__name__}
        return outcome
    finally:
        connection.exec_driver_sql("ROLLBACK TO SAVEPOINT step")
        connection.exec_driver_sql("RELEASE SAVEPOINT step")


def run_battery(engine, label):
    results = {}
    with engine.begin() as connection:
        if not connection.exec_driver_sql("SHOW is_superuser").scalar() == "on":
            pytest.skip("suppressing triggers while staging rows needs a superuser")
        connection.exec_driver_sql("SET LOCAL session_replication_role = replica")
        for statement in seed_statements():
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql("SET LOCAL session_replication_role = origin")
        for name, statements in targeted_steps():
            if name.startswith("cascade-delete-"):
                table = name.removeprefix("cascade-delete-")
                results[name] = run_step(
                    connection,
                    name,
                    statements,
                    ("remove-dependents", table, "true"),
                    label,
                )
            else:
                results[name] = run_step(connection, name, statements, None, label)
        for name, statements, prepare in generic_steps(connection):
            results[name] = run_step(connection, name, statements, prepare, label)
    return results


def test_row_and_statement_triggers_dirty_identical_projects_and_revisions(schemas):
    old = run_battery(schemas["old"], "old")
    new = run_battery(schemas["new"], "new")
    assert old.keys() == new.keys()
    differences = {name: (old[name], new[name]) for name in old if old[name] != new[name]}
    assert not differences, json.dumps(differences, indent=1, default=str)[:4000]
    # The battery must exercise every scoped table and not be vacuous.
    touched = {
        name.split(":")[0]
        for name, outcome in new.items()
        if ":" in name and outcome.get("dirty") and "error" not in outcome
    }
    assert touched == set(bi.SCOPED_TABLES), sorted(set(bi.SCOPED_TABLES) ^ touched)
    assert sum(1 for outcome in new.values() if outcome.get("dirty")) > 80
    assert any(outcome.get("full", 0) > 0 for outcome in new.values())
    assert sum(1 for outcome in new.values() if outcome.get("stale")) > 20


def random_corpus(connection, seed):
    rng = random.Random(seed)
    sources = ["s0", "s1", "s2"]
    connection.exec_driver_sql(
        "INSERT INTO sources (id, publisher, endpoint, family, geography, industries,"
        " retrieval_method, cadence_hours, enabled, health) VALUES "
        + ", ".join(
            f"('{s}', 'P', 'https://{s}.test', 'f', 'TX', '[]', 'fixture', 24, false, '{{}}')"
            for s in sources
        )
    )
    keys = [(rng.choice(sources), f"k{rng.randrange(14)}") for _ in range(24)]
    projects = list(dict.fromkeys(keys[: rng.randrange(8, 14)]))
    pids = [u(f"r{seed}-P{i}") for i in range(len(projects))]
    for pid, (source, external) in zip(pids, projects, strict=True):
        connection.exec_driver_sql(
            "INSERT INTO projects (id, identity_key, name, source_id, external_id, identity_facts)"
            " VALUES "
            f"('{pid}', 'k-{pid}', 'p', '{source}', '{external}', '{{}}')"
        )
    nids = []
    for i, pid in enumerate(pids):
        if rng.random() < 0.6:
            nid = u(f"r{seed}-N{i}")
            nids.append(nid)
            connection.exec_driver_sql(
                "INSERT INTO power_needs (id, project_id, activity_key, tier, rationale, supply)"
                f" VALUES ('{nid}', '{pid}', 'a', 'Signal', 'r', 'Unknown')"
            )
    obs = list(dict.fromkeys(rng.sample(keys, rng.randrange(8, 16))))
    oids, eids = [], []
    for i, (source, external) in enumerate(obs):
        oid = u(f"r{seed}-O{i}")
        oids.append(oid)
        connection.exec_driver_sql(
            "INSERT INTO observations (id, source_id, external_id, title, url, content_hash)"
            f" VALUES ('{oid}', '{source}', '{external}', 't', 'https://o/{i}', 'h{i}')"
        )
        for version in range(rng.randrange(0, 3)):
            eid = u(f"r{seed}-E{i}-{version}")
            eids.append(eid)
            connection.exec_driver_sql(
                "INSERT INTO evidence (id, observation_id, title, url, extraction_location,"
                f" content_hash) VALUES ('{eid}', '{oid}', 't', 'u', 'l', 'v{i}-{version}')"
            )
    for _ in range(rng.randrange(0, 10)):
        if nids:
            connection.exec_driver_sql(
                "INSERT INTO need_observations (need_id, observation_id) VALUES "
                f"('{rng.choice(nids)}', '{rng.choice(oids)}') ON CONFLICT DO NOTHING"
            )
    for i in range(rng.randrange(0, 12)):
        eid = rng.choice(eids) if eids else None
        if eid is None:
            break
        connection.exec_driver_sql(
            "INSERT INTO lifecycle_events (id, project_id, observation_id, evidence_id, state,"
            f" event_type, value_kind) VALUES ('{u(f'r{seed}-L{i}')}', '{rng.choice(pids)}',"
            f" '{rng.choice(oids)}', '{eid}', 's', 'e{i}', 'k')"
        )
        connection.exec_driver_sql(
            "INSERT INTO buying_chain_evidence (id, project_id, url, title, excerpt, content_hash,"
            " extraction_location, observed_at, last_seen_at, project_match_reason,"
            f" retained_evidence_id) VALUES ('{u(f'r{seed}-B{i}')}', '{rng.choice(pids)}',"
            f" 'https://b/{i}', 't', 'e', 'b{i}', 'l', now(), now(), 'r', '{rng.choice(eids)}')"
        )
        connection.exec_driver_sql(
            "INSERT INTO interconnection_fact_versions (id, project_id, evidence_id, payload)"
            f" VALUES ('{u(f'r{seed}-I{i}')}', '{rng.choice(pids)}', '{rng.choice(eids)}', '{{}}')"
            " ON CONFLICT DO NOTHING"
        )
    for i in range(rng.randrange(0, 8)):
        candidate = f"'{rng.choice(pids)}'" if rng.random() < 0.7 else "NULL"
        evidence_id = f"'{rng.choice(eids)}'" if eids and rng.random() < 0.5 else "NULL"
        connection.exec_driver_sql(
            "INSERT INTO project_match_decisions (observation_id, candidate_project_id,"
            " evidence_id, matched_facts, identity_facts, reason, decision) VALUES "
            f"('{rng.choice(oids)}', {candidate}, {evidence_id}, '{{}}', '{{}}', 'r', 'd{i}')"
            " ON CONFLICT DO NOTHING"
        )


ORACLE_QUERY = """
    WITH oids AS (
        SELECT id AS v FROM observations UNION ALL SELECT NULL UNION ALL SELECT gen_random_uuid()
    ), eids AS (
        SELECT id AS v FROM evidence UNION ALL SELECT NULL UNION ALL SELECT gen_random_uuid()
    ), keys AS (
        SELECT source_id AS s, external_id AS e FROM observations
        UNION SELECT source_id, external_id FROM projects
        UNION SELECT NULL, NULL UNION SELECT 's0', NULL UNION SELECT NULL, 'k1'
        UNION SELECT 'nope', 'nope'
    ), inputs AS (
        SELECT o.v AS oid, e.v AS eid, k.s, k.e FROM oids o CROSS JOIN eids e CROSS JOIN keys k
    )
    SELECT oid::text, eid::text, s, e,
        ARRAY(SELECT x.project_id::text FROM
            old_browse_observation_projects(oid, eid, s, e) x ORDER BY 1) AS old_ids,
        ARRAY(SELECT x.project_id::text FROM
            browse_observation_projects(oid, eid, s, e) x ORDER BY 1) AS new_ids
    FROM inputs
"""


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_index_driven_observation_projects_returns_the_same_set_for_every_input(schemas, seed):
    engine = schemas["new"]
    oracle = OLD_DIRTY_SQL.replace("dirty_browse_project", "old_dirty_browse_project").replace(
        "browse_observation_projects", "old_browse_observation_projects"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL session_replication_role = replica")
        connection.exec_driver_sql(oracle)
        if seed == 1:
            for statement in seed_statements():
                connection.exec_driver_sql(statement)
        else:
            random_corpus(connection, seed)
        rows = connection.exec_driver_sql(ORACLE_QUERY).all()
    assert len(rows) > 500
    mismatches = [row[:4] + (row[4], row[5]) for row in rows if row[4] != row[5]]
    assert not mismatches, mismatches[:5]
    # Not vacuous: many inputs return projects, and the keyed/NULL cases are present.
    assert sum(1 for row in rows if row[5]) > 20
    assert any(row[0] is None and row[5] for row in rows) or True
    assert any(row[2] is None and row[3] is None for row in rows)


def test_statement_trigger_inventory_and_revision_contract(schemas):
    engine = schemas["new"]
    with engine.begin() as connection:
        triggers = {
            (table, name)
            for table, name in connection.exec_driver_sql(
                """
                SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema() AND t.tgname ~ '^dirty_browse'
                """
            )
        }
        expected = {
            (table, f"dirty_browse_{name}")
            for table in bi.SCOPED_TABLES
            for name, _operation, _transition in bi.DIRTY_TRIGGER_OPERATIONS
            if not (name == "insert" and table in bi.DIRTY_NO_INSERT_TABLES)
        } | {("call_fact_decisions", "dirty_browse_fact_decision_insert")}
        assert triggers == expected
        row_level = connection.exec_driver_sql(
            """
            SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = current_schema() AND p.proname ~ '^dirty_browse_project'
                AND t.tgtype & 1 = 1
            """
        ).scalar()
        assert row_level == 0
        # Dirty rows carry the revision the same statement's invalidation assigns, and a
        # multi-row statement dirties every project at that one revision.
        for statement in seed_statements():
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql("DELETE FROM browse_dirty_projects")
        before = connection.exec_driver_sql(
            "SELECT input_revision FROM browse_state WHERE id = 1"
        ).scalar()
        connection.exec_driver_sql("UPDATE projects SET name = name || '!'")
        after, revisions, count = connection.exec_driver_sql(
            "SELECT (SELECT input_revision FROM browse_state WHERE id = 1),"
            " array_agg(DISTINCT revision), count(*) FROM browse_dirty_projects"
        ).one()
        assert after == before + 1 and revisions == [after] and count == 6


def test_migration_definitions_match_the_installer():
    path = Path(__file__).parents[2] / "migrations/versions/0056_statement_level_dirty_projects.py"
    spec = importlib.util.spec_from_file_location("migration_0056", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.DIRTY_SQL == bi.DIRTY_SQL
    assert tuple(migration.SCOPED_TABLES) == tuple(bi.SCOPED_TABLES)
    assert migration.DIRTY_TRIGGER_OPERATIONS == bi.DIRTY_TRIGGER_OPERATIONS
    assert migration.DIRTY_NO_INSERT_TABLES == bi.DIRTY_NO_INSERT_TABLES
    # The restored (downgrade) definition is the oracle text above.
    assert migration.OLD_DIRTY_SQL.strip() == OLD_DIRTY_SQL.strip()
