import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.export_review_sample import build_export

from gridlens.persistence.models import Evidence, Observation


class Result:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class ReadSession:
    def __init__(self):
        self.evidence_calls = 0
        self.link_calls = 0
        self.observations = [
            Observation(
                id=UUID("00000000-0000-0000-0000-000000000002"),
                source_id="nc-commerce",
                external_id="2",
                title="Second",
                abstract="Retained excerpt 2",
                published_at=None,
                url="https://example.test/2",
                content_hash="b" * 64,
            ),
            Observation(
                id=UUID("00000000-0000-0000-0000-000000000001"),
                source_id="nc-commerce",
                external_id="1",
                title="First",
                abstract="Retained excerpt 1",
                published_at=date(2026, 1, 1),
                url="https://example.test/1",
                content_hash="a" * 64,
            ),
        ]
        self.evidence = Evidence(
            id=UUID("00000000-0000-0000-0000-000000000003"),
            observation_id=self.observations[0].id,
            content_hash="c" * 64,
            title="Retained evidence title",
            abstract="Retained evidence excerpt",
            url="https://example.test/evidence",
            published_at=None,
            observed_at=datetime(2026, 1, 3, tzinfo=UTC),
            extraction_location="abstract",
            event_date=None,
        )
        self.source = SimpleNamespace(
            publisher="NC Commerce",
            family="state",
            geography="North Carolina",
            industries=["manufacturing"],
        )
        self.active = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000004"),
            active=True,
            tier="Signal",
            rationale="Stored rationale",
            activity_key="facility",
        )
        self.inactive = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000005"),
            active=False,
            tier="Signal",
            rationale="Retained but inactive",
            activity_key="facility",
        )
        self.project = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000006"),
            name="Example facility",
            location="Example County, North Carolina",
        )

    def scalars(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Observation:
            return Result(self.observations)
        self.evidence_calls += 1
        return Result([] if self.evidence_calls == 1 else [self.evidence])

    def get(self, model, key):
        return self.source

    def execute(self, statement):
        self.link_calls += 1
        if self.link_calls == 1:
            return Result([])
        return Result(
            [
                (None, self.active, self.project),
                (None, self.inactive, self.project),
            ]
        )


def test_export_preserves_retained_and_active_inactive_admissions_and_evidence_attribution():
    result = build_export(ReadSession())

    records = result["observations"]
    assert [record["observation_id"] for record in records] == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    assert records[0]["admissions"] == []
    retained = records[1]
    assert retained["evidence"][0]["abstract"] == "Retained evidence excerpt"
    assert retained["evidence"][0]["url"] == "https://example.test/evidence"
    assert retained["published_at"] is None
    assert retained["evidence"][0]["published_at"] is None
    assert [item["active"] for item in retained["admissions"]] == [True, False]
    assert retained["admissions"][1]["rationale"] == "Retained but inactive"
    assert result["scope"]["limits"]
