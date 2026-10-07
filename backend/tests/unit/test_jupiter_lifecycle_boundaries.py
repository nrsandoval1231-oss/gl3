"""Paraphrased Jupiter cases and synthetic controls; never live project evidence."""

from datetime import date

import pytest

from gridlens.domain.lifecycle import classify_event
from gridlens.domain.project_research import extract_project_claims
from gridlens.intelligence.lifecycle_service import lifecycle_event_supported
from gridlens.persistence.models import Evidence, Interpretation, Project


@pytest.mark.parametrize(
    "text",
    [
        "Project Jupiter data center campus has building permits. The adjacent microgrid "
        "air permit remains pending.",
        "Court allows Project Jupiter data center air permit proceedings to resume.",
        "Hearing officer appointed for the Project Jupiter data center air permit.",
        "Oracle issued a force-majeure notice for Project Jupiter data center over potential "
        "power delays; the project remains on schedule.",
        "Project Jupiter data center microgrid awaits utility service; campus building "
        "permits are separate.",
    ],
)
def test_multitrack_reports_do_not_become_single_campus_milestones(text):
    assert classify_event(text) is None


def test_historical_accepted_mixed_report_cannot_keep_lifecycle_support():
    project = Project(identity_key="jupiter", name="Project Jupiter")
    evidence = Evidence(
        content_hash="abc",
        title="Project Jupiter data center microgrid awaits utility service",
        abstract=None,
    )
    interpretation = Interpretation(
        status="accepted",
        assessment={
            "evidence_hash": "abc",
            "project_identity_key": "jupiter",
        },
    )
    assert not lifecycle_event_supported("utility_service", evidence, interpretation, project)


def test_single_facility_permit_still_supports_campus_construction():
    event = classify_event("Building permit issued for Project Jupiter data center campus")
    assert event is not None and event.state == "construction"
    project = Project(identity_key="jupiter", name="Project Jupiter")
    evidence = Evidence(
        content_hash="abc",
        title="Building permit issued for Project Jupiter data center campus",
        abstract=None,
    )
    interpretation = Interpretation(
        status="accepted",
        assessment={
            "evidence_hash": "abc",
            "project_identity_key": "jupiter",
        },
    )
    assert lifecycle_event_supported("construction", evidence, interpretation, project)


@pytest.mark.parametrize(
    "text",
    [
        "Project Jupiter force majeure notice concerns potential power delays.",
        "Project Jupiter microgrid construction is paused.",
        "Project Jupiter air permit proceedings are stayed.",
        "Project Jupiter remains on schedule.",
    ],
)
def test_risk_procedure_and_schedule_claims_do_not_cancel_or_energize_campus(text):
    assert (
        extract_project_claims(
            text,
            references=["Project Jupiter"],
            activity_key="construction",
            published_at=date(2026, 9, 24),
            today=date(2026, 10, 7),
        )
        == []
    )
