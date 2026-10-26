"""Exceptional membership removal preserves source identity and refresh history."""

import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.customer_accounts import record_rrc_operator_membership
from gridlens.intelligence.membership_corrections import (
    MembershipCorrectionConflict,
    retract_project_membership,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    CompanyIdentity,
    CompanyProjectMembership,
    CompanyProjectMembershipCorrection,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def membership_runtime():
    url = make_url(settings.test_database_url)
    assert url.database and url.database.endswith("_test")
    assert url != make_url(settings.database_url)
    schema = "membership_exception_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    source_id = "texas-rrc-flare-vent-exceptions"
    body = "Operator number: 217012\nOperator: DIAMONDBACK E&P LLC"
    digest = hashlib.sha256(body.encode()).hexdigest()
    with factory.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Synthetic RRC source",
                endpoint="https://rrc.example",
                family="oil-and-gas-permits",
                geography="Texas",
                industries=["oil-and-gas"],
                retrieval_method="rrc-flare-exceptions",
            )
        )
        session.flush()
        project = Project(
            identity_key="synthetic-membership-exception",
            name="Synthetic RRC site",
            location="100 Synthetic Road, Dallas, TX",
            source_id=source_id,
            external_id="synthetic-rrc-1",
        )
        observation = Observation(
            source_id=source_id,
            external_id=project.external_id,
            title="Synthetic source row",
            abstract=body,
            url="https://rrc.example/synthetic-rrc-1",
            content_hash=digest,
        )
        session.add_all([project, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            title=observation.title,
            abstract=body,
            url=observation.url,
            content_hash=digest,
            extraction_location="Synthetic RRC row",
        )
        need = PowerNeed(
            project_id=project.id,
            activity_key="flaring",
            tier="Signal",
            rationale="Synthetic fixture",
            supply="Unknown",
        )
        session.add_all([evidence, need])
        session.flush()
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=digest,
            status="accepted",
            evaluator_version="synthetic-exception-test",
            assessment={"decision": "accepted", "evidence_hash": evidence.content_hash},
        )
        session.add_all(
            [interpretation, NeedObservation(need_id=need.id, observation_id=observation.id)]
        )
        session.flush()
        record = {
            "abstract": body,
            "permit": {
                "source_type": source_id,
                "operator_number": "217012",
                "operator": "DIAMONDBACK E&P LLC",
            },
        }
        record_rrc_operator_membership(
            session,
            project=project,
            observation=observation,
            evidence=evidence,
            source_id=source_id,
            record=record,
        )
        member = session.scalar(select(CompanyProjectMembership))
        assert member is not None
        request = {
            "membership_id": member.id,
            "project_id": project.id,
            "company_id": member.company_identity_id,
            "expected_version": 0,
            "expected_source_evidence_id": evidence.id,
            "expected_source_hash": evidence.content_hash,
            "idempotency_key": "synthetic-reviewed-retraction",
            "actor": "test reviewer",
            "reason": "Source organization attribution was disputed in this synthetic fixture",
        }
        ids = observation.id, interpretation.id, evidence.id, need.id
    yield factory, request, ids, record
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def test_scoped_retraction_replay_checks_every_reviewed_boundary(membership_runtime):
    factory, request, _ids, _record = membership_runtime
    with factory.begin() as session:
        event = retract_project_membership(session, **request)
        event_id = event.id
    with factory.begin() as session:
        assert retract_project_membership(session, **request).id == event_id
    for mutation, error in (
        ({"project_id": uuid4()}, LookupError),
        ({"company_id": uuid4()}, LookupError),
        ({"expected_source_evidence_id": uuid4()}, MembershipCorrectionConflict),
        ({"expected_source_hash": "f" * 64}, MembershipCorrectionConflict),
        ({"reason": "Different review reason"}, MembershipCorrectionConflict),
        ({"actor": "Different reviewer"}, MembershipCorrectionConflict),
        ({"expected_version": 1}, MembershipCorrectionConflict),
        ({"idempotency_key": "second-request"}, MembershipCorrectionConflict),
    ):
        with factory.begin() as session, pytest.raises(error):
            retract_project_membership(session, **{**request, **mutation})
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(CompanyProjectMembershipCorrection))
            == 1
        )
        member = session.get(CompanyProjectMembership, request["membership_id"])
        assert (member.state, member.version) == ("retracted", 1)
        assert (member.project_id, member.company_identity_id) == (
            request["project_id"],
            request["company_id"],
        )
        assert member.source_evidence_id == request["expected_source_evidence_id"]
        assert member.source_version_hash == request["expected_source_hash"]


def test_concurrent_retractions_cannot_advance_the_same_version_twice(membership_runtime):
    factory, request, _ids, _record = membership_runtime
    barrier = Barrier(2)

    def retract(index):
        try:
            with factory.begin() as session:
                barrier.wait(timeout=10)
                retract_project_membership(
                    session, **{**request, "idempotency_key": f"concurrent-{index}"}
                )
            return "recorded"
        except MembershipCorrectionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(retract, (1, 2)))
    assert sorted(outcomes) == ["conflict", "recorded"]
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(CompanyProjectMembershipCorrection))
            == 1
        )
        assert session.get(CompanyProjectMembership, request["membership_id"]).version == 1


def test_source_refresh_preserves_retraction_and_original_evidence(membership_runtime):
    factory, request, ids, record = membership_runtime
    observation_id, interpretation_id, evidence_id, need_id = ids
    with factory.begin() as session:
        retract_project_membership(session, **request)
    with factory.begin() as session:
        observation = session.get(Observation, observation_id)
        original = session.get(Evidence, evidence_id)
        replacement = Evidence(
            observation_id=observation_id,
            content_hash=hashlib.sha256(b"synthetic-refreshed-source").hexdigest(),
            title=original.title,
            abstract=original.abstract,
            url=original.url,
            observed_at=datetime.now(UTC),
            extraction_location="Synthetic refreshed source version",
        )
        session.add(replacement)
        session.flush()
        interpretation = session.get(Interpretation, interpretation_id)
        interpretation.assessment = {
            **interpretation.assessment,
            "evidence_hash": replacement.content_hash,
        }
        record_rrc_operator_membership(
            session,
            project=session.get(Project, request["project_id"]),
            observation=observation,
            evidence=replacement,
            source_id=observation.source_id,
            record=record,
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CompanyProjectMembership)) == 1
        assert session.get(CompanyProjectMembership, request["membership_id"]).state == "retracted"
        assert (
            session.scalar(select(func.count()).select_from(CompanyProjectMembershipCorrection))
            == 1
        )
        assert session.get(Evidence, evidence_id).content_hash == request["expected_source_hash"]
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(CompanyIdentity)) == 1
        assert session.get(PowerNeed, need_id).tier == "Signal"


def test_internal_cli_is_read_only_until_explicit_execution(
    membership_runtime, monkeypatch, capsys
):
    factory, request, _ids, _record = membership_runtime
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "membership_exception_cli", root / "scripts" / "retract_project_membership.py"
    )
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "SessionLocal", factory)
    arguments = [
        "--membership-id",
        str(request["membership_id"]),
        "--project-id",
        str(request["project_id"]),
        "--company-id",
        str(request["company_id"]),
        "--expected-version",
        "0",
        "--source-evidence-id",
        str(request["expected_source_evidence_id"]),
        "--source-hash",
        request["expected_source_hash"],
        "--actor",
        request["actor"],
        "--reason",
        request["reason"],
        "--idempotency-key",
        request["idempotency_key"],
        "--expected-database-name",
        make_url(settings.test_database_url).database,
    ]
    with pytest.raises(SystemExit):
        cli.main([*arguments[:-1], "not-the-reviewed-database", "--execute"])
    capsys.readouterr()
    cli.main(arguments)
    assert json.loads(capsys.readouterr().out)["status"] == "preview"
    with factory() as session:
        assert session.get(CompanyProjectMembership, request["membership_id"]).state == "current"
        assert (
            session.scalar(select(func.count()).select_from(CompanyProjectMembershipCorrection))
            == 0
        )
    cli.main([*arguments, "--execute"])
    assert json.loads(capsys.readouterr().out)["status"] == "executed"
    with factory() as session:
        assert session.get(CompanyProjectMembership, request["membership_id"]).state == "retracted"
