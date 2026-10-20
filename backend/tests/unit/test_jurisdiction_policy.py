"""Behavioral gates; all activation examples are synthetic, not enacted city facts."""

from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError


def parse(data):
    from gridlens.domain.jurisdiction_policy import PolicyRecord

    return PolicyRecord.model_validate(data)


@pytest.fixture
def pending():
    return dict(
        schema_version=1,
        policy_id="test-moratorium",
        jurisdiction="Test City, CA",
        kind="land_use_moratorium",
        scope="New data-center land-use approvals citywide",
        as_of_date="2026-10-07",
        duration_days=45,
        evidence=[
            dict(
                id="status",
                url="https://example.gov/file/1",
                observed_on="2026-10-07",
                location="Status",
                kind="official_record",
                summary="Passed; final action October 6; minutes draft",
            )
        ],
        observations=[dict(source_id="status", status="Passed", event_date="2026-10-06")],
        limitations=["Enactment and effective interval not verified"],
    )


def enacted(pending):
    data = deepcopy(pending)
    data["evidence"] += [
        dict(
            id="enactment",
            url="https://example.gov/ordinance/1",
            observed_on="2026-10-07",
            location="Signed adoption",
            kind="enactment_record",
            summary="Enacted October 6",
        ),
        dict(
            id="interval",
            url="https://example.gov/ordinance/1",
            observed_on="2026-10-07",
            location="Effective clause",
            kind="effective_clause",
            summary="Verified interval",
        ),
    ]
    data["enactment"] = dict(date="2026-10-06", source_id="enactment")
    data["effective_interval"] = dict(
        start="2026-10-06", end_exclusive="2026-11-20", source_id="interval"
    )
    return data


@pytest.mark.parametrize("status", ["In Council", "Mayors Office", "Passed", "Approved"])
def test_legistar_status_never_substitutes_for_enactment(pending, status):
    pending["observations"][0]["status"] = status
    assert parse(pending).state_on(date(2026, 10, 7)) == "pending_verification"


def test_enactment_alone_does_not_activate(pending):
    data = enacted(pending)
    del data["effective_interval"]
    assert parse(data).state_on(date(2026, 10, 7)) == "pending_verification"


def test_future_active_and_expired_transitions_preserve_prior_observations(pending):
    data = enacted(pending)
    data["effective_interval"].update(start="2026-10-08", end_exclusive="2026-11-22")
    record = parse(data)
    assert record.state_on(date(2026, 10, 7)) == "enacted_not_effective"
    assert record.state_on(date(2026, 10, 8)) == "operative"
    assert record.state_on(date(2026, 11, 21)) == "operative"
    assert record.state_on(date(2026, 11, 22)) == "expired"
    assert record.observations[0].status == "Passed"
    assert record.model_dump(mode="json")["observations"] == data["observations"]


@pytest.mark.parametrize("field", ["enactment", "effective_interval"])
def test_draft_or_status_evidence_cannot_activate(pending, field):
    data = enacted(pending)
    data[field]["source_id"] = "status"
    with pytest.raises(ValidationError):
        parse(data)


def test_effective_interval_without_enactment_is_rejected(pending):
    data = enacted(pending)
    del data["enactment"]
    with pytest.raises(ValidationError):
        parse(data)


@pytest.mark.parametrize(
    "change",
    [
        "reversed",
        "before_enactment",
        "unknown_source",
        "future_evidence",
        "duplicate_source",
        "project_id",
    ],
)
def test_invalid_provenance_and_project_scope_rejected(pending, change):
    data = enacted(pending)
    if change == "reversed":
        data["effective_interval"]["end_exclusive"] = "2026-10-05"
    elif change == "before_enactment":
        data["effective_interval"]["start"] = "2026-10-05"
    elif change == "unknown_source":
        data["observations"][0]["source_id"] = "missing"
    elif change == "future_evidence":
        data["evidence"][0]["observed_on"] = "2026-10-08"
    elif change == "duplicate_source":
        data["evidence"].append(data["evidence"][0])
    else:
        data["project_id"] = "cannot-infer-denial"
    with pytest.raises(ValidationError):
        parse(data)


@pytest.mark.parametrize(
    "kind,want",
    [
        ("utility_intake_constraint", "reported_constraint"),
        ("policy_development", "in_development"),
    ],
)
def test_non_land_use_records_cannot_become_moratoria(pending, kind, want):
    pending["kind"] = kind
    pending.pop("duration_days")
    assert parse(pending).state_on(date(2026, 10, 7)) == want
    data = enacted(pending)
    with pytest.raises(ValidationError):
        parse(data)


def test_as_of_projection_cannot_use_future_knowledge(pending):
    with pytest.raises(ValueError):
        parse(pending).state_on(date(2026, 10, 6))


@pytest.mark.parametrize("kind", ["utility_intake_constraint", "policy_development"])
def test_non_moratorium_snapshot_does_not_assert_future_conditions(pending, kind):
    pending["kind"] = kind
    pending.pop("duration_days")
    assert parse(pending).state_on(date(2028, 1, 1)) == "requires_refresh"


@pytest.mark.parametrize(
    "name,want",
    [
        ("sf-261021", "pending_verification"),
        ("oakland-27-0050", "pending_verification"),
        ("santa-clara-svp-intake", "reported_constraint"),
        ("santa-clara-policy-development", "in_development"),
    ],
)
def test_reviewed_records_roundtrip_without_project_claims(name, want):
    from gridlens.domain.jurisdiction_policy import PolicyRecord, load_policy

    path = Path(__file__).parents[3] / "config/policies" / f"{name}.json"
    record = load_policy(path)
    assert record.state_on(date(2026, 10, 7)) == want
    assert PolicyRecord.model_validate_json(record.model_dump_json()) == record
    assert record.enactment is None
    assert record.effective_interval is None
