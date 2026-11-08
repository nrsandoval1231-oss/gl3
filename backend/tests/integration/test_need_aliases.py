"""Synthetic retained-data checks for the conservative need-alias overlay."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.need_aliases import (
    NeedAliasError,
    canonical_need_map,
    record_alias,
    resolve_component,
    retract_alias,
)
from gridlens.persistence.commercial_pursuit_models import CommercialPursuit
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    NeedAliasAssertion,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def alias_env():
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL need-alias tests")
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    schema = "need_alias_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def _fixture_graph(factory, *, scope="package-7"):
    with factory() as session:
        source = Source(
            id=f"src-{uuid4().hex[:8]}",
            publisher="Synthetic registry",
            endpoint="https://synthetic.invalid",
            family="synthetic-test",
            geography="Synthetic",
            industries=["synthetic"],
            retrieval_method="fixture",
        )
        session.add(source)
        session.flush()
        needs = []
        projects = []
        for label in ("left", "root", "other"):
            project = Project(
                identity_key=f"synthetic-{uuid4()}",
                name="Synthetic site",
                location="Synthetic, TX",
                source_id=source.id,
                external_id=f"record-{label}-{uuid4().hex[:8]}",
            )
            session.add(project)
            session.flush()
            need = PowerNeed(
                project_id=project.id,
                activity_key=f"package-{label}",
                tier="Lead",
                rationale="Synthetic fixture only",
            )
            session.add(need)
            projects.append(project)
            needs.append(need)
        same_project_need = PowerNeed(
            project_id=projects[0].id,
            activity_key="package-left-distinct",
            tier="Lead",
            rationale="Synthetic separate package fixture",
        )
        session.add(same_project_need)
        needs.append(same_project_need)
        session.flush()
        left_binding = {
            "source_ref": f"{projects[0].source_id}:{projects[0].external_id}",
            "activity_key": needs[0].activity_key,
            "package_scope": scope,
        }
        root_binding = {
            "source_ref": f"{projects[1].source_id}:{projects[1].external_id}",
            "activity_key": needs[1].activity_key,
            "package_scope": scope,
        }
        quote = (
            f"Package {scope}: {left_binding['source_ref']} ({left_binding['activity_key']}) "
            f"and {root_binding['source_ref']} ({root_binding['activity_key']}) "
            "refer to the same power package."
        )
        observation = Observation(
            source_id=source.id,
            external_id=f"alias-evidence-{uuid4().hex[:8]}",
            title=quote,
            abstract="Synthetic alias basis",
            url="https://synthetic.invalid/evidence",
            content_hash="a" * 64,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            provenance={
                "need_alias_assertion": {
                    "package_scope": scope,
                    "need_bindings": [left_binding, root_binding],
                    "same_package_quote": quote,
                }
            },
        )
        session.add(evidence)
        session.flush()
        session.add_all(
            [
                NeedObservation(need_id=needs[0].id, observation_id=observation.id),
                NeedObservation(need_id=needs[1].id, observation_id=observation.id),
                NeedObservation(need_id=needs[3].id, observation_id=observation.id),
            ]
        )
        session.commit()
        return tuple(n.id for n in needs), observation.id, evidence.id


def _record(
    session,
    needs,
    evidence_id,
    *,
    scope="package-7",
    alias_index=0,
    canonical_index=1,
):
    evidence = session.get(Evidence, evidence_id)
    return record_alias(
        session,
        alias_need_id=needs[alias_index],
        canonical_need_id=needs[canonical_index],
        evidence_id=evidence_id,
        expected_evidence_hash=evidence.content_hash,
        package_scope=scope,
        reason="Explicit source package cross-reference",
    )


def _add_pair_evidence(session, needs, left_index, right_index, *, scope="package-7"):
    left = session.get(PowerNeed, needs[left_index])
    right = session.get(PowerNeed, needs[right_index])
    left_project = session.get(Project, left.project_id)
    right_project = session.get(Project, right.project_id)
    bindings = [
        {
            "source_ref": f"{project.source_id}:{project.external_id}",
            "activity_key": need.activity_key,
            "package_scope": scope,
        }
        for need, project in ((left, left_project), (right, right_project))
    ]
    quote = (
        f"Package {scope}: {bindings[0]['source_ref']} ({bindings[0]['activity_key']}) and "
        f"{bindings[1]['source_ref']} ({bindings[1]['activity_key']}) "
        "refer to the same power package."
    )
    source = session.get(Source, left_project.source_id)
    digest = uuid4().hex + uuid4().hex
    observation = Observation(
        source_id=source.id,
        external_id=f"alias-evidence-{uuid4().hex[:8]}",
        title=quote,
        abstract="Synthetic alias basis",
        url="https://synthetic.invalid/evidence",
        content_hash=digest,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=digest,
        title=quote,
        abstract=observation.abstract,
        url=observation.url,
        provenance={
            "need_alias_assertion": {
                "package_scope": scope,
                "need_bindings": bindings,
                "same_package_quote": quote,
            }
        },
    )
    session.add(evidence)
    session.flush()
    session.add_all(
        [
            NeedObservation(need_id=left.id, observation_id=observation.id),
            NeedObservation(need_id=right.id, observation_id=observation.id),
        ]
    )
    session.flush()
    return evidence.id


def test_alias_is_idempotent_and_resolves_one_existing_pursuit(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        assertion = _record(session, needs, evidence_id)
        session.commit()
        first_id = assertion.id
        pursuit = CommercialPursuit(
            need_id=needs[1], project_id=session.get(PowerNeed, needs[1]).project_id
        )
        session.add(pursuit)
        session.commit()
        replay = _record(session, needs, evidence_id)
        assert replay.id == first_id
        resolution = resolve_component(session, needs[0])
        assert resolution.root_need_id == needs[1]
        assert set(resolution.member_need_ids) == set(needs[:2])
        assert resolution.existing_pursuit.id == pursuit.id
        assert not resolution.conflicted


def test_inactive_canonical_still_resolves_existing_pursuit_retry(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, evidence_id)
        canonical = session.get(PowerNeed, needs[1])
        pursuit = CommercialPursuit(need_id=needs[1], project_id=canonical.project_id)
        session.add(pursuit)
        canonical.active = False
        session.commit()
        resolution = resolve_component(session, needs[0])
        pursuits = session.scalars(
            select(CommercialPursuit).where(CommercialPursuit.need_id.in_(needs[:2]))
        ).all()
        assert resolution.root_need_id == needs[1]
        assert resolution.existing_pursuit.id == pursuit.id
        assert len(pursuits) == 1


def test_canonical_need_map_keeps_current_alias_for_inactive_need(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
        session.get(PowerNeed, needs[1]).active = False
        session.get(PowerNeed, needs[0]).active = False
        session.commit()
        assert canonical_need_map(session) == {needs[0]: needs[1]}


def test_canonical_need_map_drops_retracted_alias(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
        retract_alias(session, needs[0], "Synthetic source withdrawal")
        session.commit()
        assert canonical_need_map(session) == {}


def test_canonical_need_map_drops_stale_and_source_unsupported_links(alias_env):
    stale_needs, stale_observation_id, stale_evidence_id = _fixture_graph(alias_env)
    text_needs, text_observation_id, text_evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, stale_needs, stale_evidence_id)
        _record(session, text_needs, text_evidence_id)
        session.commit()
        stale_observation = session.get(Observation, stale_observation_id)
        stale_observation.content_hash = "c" * 64
        session.commit()
        assert canonical_need_map(session) == {text_needs[0]: text_needs[1]}
        observation = session.get(Observation, text_observation_id)
        evidence = session.get(Evidence, text_evidence_id)
        evidence.title = "Source text no longer has the package assertion"
        observation.title = evidence.title
        session.commit()
        assert canonical_need_map(session) == {}


def test_canonical_need_map_query_count_is_independent_of_alias_count(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
        statements = []
        bind = session.get_bind()

        def capture_statement(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(bind, "before_cursor_execute", capture_statement)
        try:
            one_alias_map = canonical_need_map(session)
            one_alias_query_count = len(statements)
            statements.clear()
            second_evidence_id = _add_pair_evidence(session, needs, 2, 1)
            _record(
                session,
                needs,
                second_evidence_id,
                alias_index=2,
                canonical_index=1,
            )
            session.commit()
            statements.clear()
            mapping = canonical_need_map(session)
        finally:
            event.remove(bind, "before_cursor_execute", capture_statement)
        assert one_alias_map == {needs[0]: needs[1]}
        assert mapping == {needs[0]: needs[1], needs[2]: needs[1]}
        assert one_alias_query_count == 5
        assert len(statements) == 5


@pytest.mark.parametrize("right_index", [0, 2])
def test_canonical_need_map_fails_closed_on_malformed_chain_or_cycle(alias_env, right_index):
    needs, _observation_id, first_evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, first_evidence_id)
        session.commit()
        second_evidence_id = _add_pair_evidence(session, needs, 1, right_index)
        evidence = session.get(Evidence, second_evidence_id)
        claim = evidence.provenance["need_alias_assertion"]
        session.add(
            NeedAliasAssertion(
                alias_need_id=needs[1],
                canonical_need_id=needs[right_index],
                evidence_id=second_evidence_id,
                evidence_hash=evidence.content_hash,
                package_scope="package-7",
                basis=claim,
                reason="Synthetic malformed graph fixture",
                state="current",
                version=1,
            )
        )
        session.commit()
        with pytest.raises(NeedAliasError, match="chain or cycle"):
            canonical_need_map(session)


def test_scope_and_stale_evidence_are_rejected(alias_env):
    needs, observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        unrelated_need = resolve_component(session, needs[2])
        assert unrelated_need.member_need_ids == (needs[2],)
        with pytest.raises(NeedAliasError, match="package scope"):
            _record(session, needs, evidence_id, scope="different-package")
        with pytest.raises(NeedAliasError, match="both source records"):
            _record(session, needs, evidence_id, alias_index=3)
        evidence = session.get(Evidence, evidence_id)
        evidence.title = "No package identifiers retained in the source text"
        observation = session.get(Observation, observation_id)
        observation.title = evidence.title
        session.flush()
        with pytest.raises(NeedAliasError, match="affirmative same-package line"):
            _record(session, needs, evidence_id)
        observation = session.get(Observation, observation_id)
        observation.content_hash = "b" * 64
        session.flush()
        with pytest.raises(NeedAliasError, match="no longer current"):
            _record(session, needs, evidence_id)


def test_ambiguous_separate_package_statement_abstains(alias_env):
    needs, _observation_id, _evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        evidence_id = _add_pair_evidence(session, needs, 0, 1)
        evidence = session.get(Evidence, evidence_id)
        observation = session.get(Observation, evidence.observation_id)
        observation.abstract = "Package package-7: these are separate power packages."
        evidence.abstract = observation.abstract
        session.flush()
        with pytest.raises(NeedAliasError, match="affirmative same-package line"):
            _record(session, needs, evidence_id)


def test_retraction_stops_redirect_but_keeps_assertion_history(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
        retraction = retract_alias(session, needs[0], "Source withdrew package link")
        session.commit()
        resolution = resolve_component(session, needs[0])
        history = session.scalars(
            select(NeedAliasAssertion).where(NeedAliasAssertion.alias_need_id == needs[0])
        ).all()
        assert retraction.state == "retracted"
        assert resolution.root_need_id == needs[0]
        assert set(resolution.member_need_ids) == {needs[0]}
        assert {row.state for row in history} == {"superseded", "retracted"}


def test_resolution_rechecks_source_text(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
        evidence = session.get(Evidence, evidence_id)
        observation = session.get(Observation, evidence.observation_id)
        evidence.title = "Withdrawn cross-reference"
        evidence.abstract = "Withdrawn cross-reference"
        observation.title = "Withdrawn cross-reference"
        observation.abstract = "Withdrawn cross-reference"
        session.commit()
        resolution = resolve_component(session, needs[0])
        assert resolution.root_need_id == needs[0]
        assert resolution.member_need_ids == (needs[0],)


def test_alias_cycle_is_rejected(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
        with pytest.raises(NeedAliasError, match="canonical target"):
            record_alias(
                session,
                alias_need_id=needs[1],
                canonical_need_id=needs[0],
                evidence_id=evidence_id,
                expected_evidence_hash="a" * 64,
                package_scope="package-7",
                reason="Synthetic reverse edge",
            )


def test_reparenting_with_incoming_alias_is_rejected_and_pursuits_survive(alias_env):
    needs, _observation_id, first_evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        first_pursuit = CommercialPursuit(
            need_id=needs[0], project_id=session.get(PowerNeed, needs[0]).project_id
        )
        third_pursuit = CommercialPursuit(
            need_id=needs[2], project_id=session.get(PowerNeed, needs[2]).project_id
        )
        session.add_all([first_pursuit, third_pursuit])
        session.commit()
        _record(session, needs, first_evidence_id)
        session.commit()
        second_evidence_id = _add_pair_evidence(session, needs, 1, 2)
        with pytest.raises(NeedAliasError, match="incoming aliases"):
            _record(
                session,
                needs,
                second_evidence_id,
                alias_index=1,
                canonical_index=2,
            )
        session.rollback()
        aliases = session.scalars(
            select(NeedAliasAssertion).where(NeedAliasAssertion.state == "current")
        ).all()
        pursuits = session.scalars(
            select(CommercialPursuit).where(
                CommercialPursuit.id.in_([first_pursuit.id, third_pursuit.id])
            )
        ).all()
        assert [(row.alias_need_id, row.canonical_need_id) for row in aliases] == [
            (needs[0], needs[1])
        ]
        assert {row.id for row in pursuits} == {first_pursuit.id, third_pursuit.id}


def test_multiple_existing_pursuits_preserve_histories_and_conflict(alias_env):
    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        for need_id in needs[:2]:
            need = session.get(PowerNeed, need_id)
            session.add(CommercialPursuit(need_id=need_id, project_id=need.project_id))
        session.commit()
        assertion = _record(session, needs, evidence_id)
        replay = _record(session, needs, evidence_id)
        session.commit()
        resolution = resolve_component(session, needs[0])
        pursuits = session.scalars(
            select(CommercialPursuit).where(CommercialPursuit.need_id.in_(needs[:2]))
        ).all()
        assert assertion.state == "conflicted"
        assert replay.id == assertion.id
        assert resolution.root_need_id == needs[0]
        assert resolution.conflicted
        assert resolution.existing_pursuit is None
        assert len(pursuits) == 2


def test_retracted_conflict_history_does_not_block_new_current_alias(alias_env):
    needs, _observation_id, first_evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        for need_id in needs[:2]:
            need = session.get(PowerNeed, need_id)
            session.add(CommercialPursuit(need_id=need_id, project_id=need.project_id))
        session.commit()
        conflicted = _record(session, needs, first_evidence_id)
        session.commit()
        assert conflicted.state == "conflicted"
        retraction = retract_alias(session, needs[0], "Resolve prior pursuit conflict")
        session.commit()
        corrected_evidence_id = _add_pair_evidence(session, needs, 0, 2)
        corrected = _record(
            session,
            needs,
            corrected_evidence_id,
            alias_index=0,
            canonical_index=2,
        )
        session.commit()
        resolution = resolve_component(session, needs[0])
        history = session.scalars(
            select(NeedAliasAssertion).where(NeedAliasAssertion.alias_need_id == needs[0])
        ).all()
        assert retraction.state == "retracted"
        assert corrected.state == "current"
        assert resolution.root_need_id == needs[2]
        assert not resolution.conflicted
        assert resolution.existing_pursuit is not None
        assert {row.state for row in history} >= {
            "conflicted",
            "retracted",
            "current",
        }


def test_migration_empty_rollback_and_nonempty_history_guard(alias_env):
    migration_path = (
        Path(__file__).parents[2] / "migrations" / "versions" / "0051_canonical_need_aliases.py"
    )
    spec = spec_from_file_location("canonical_need_aliases_migration", migration_path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = alias_env.kw["bind"]
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE need_alias_assertions"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
        assert sa.inspect(connection).has_table("need_alias_assertions")

    needs, _observation_id, evidence_id = _fixture_graph(alias_env)
    with alias_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with pytest.raises(RuntimeError, match="Refusing to drop retained"):
            with Operations.context(context):
                migration.downgrade()
        assert sa.inspect(connection).has_table("need_alias_assertions")
