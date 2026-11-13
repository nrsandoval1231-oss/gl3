"""Operational target scoping must accept the extractor's copular wording."""

from gridlens.domain.customer_intelligence import extract_customer_facts
from gridlens.intelligence.customer_intelligence import scope_customer_facts

SOURCE = {"url": "https://example.test/project", "content_hash": "c" * 64}
PROJECT = "Mock Permian Compression Station"


def scoped(text: str) -> list[dict]:
    payload = extract_customer_facts(text, project_id="project-1", source=SOURCE)
    result = scope_customer_facts(payload, PROJECT, source_text=text)
    return result["timeline_claims"]


def test_copular_expected_operational_deadline_and_within_target_are_scoped():
    deadline = scoped(f"{PROJECT} is expected to be operational by 2027.")
    within = scoped(f"{PROJECT} is expected to be operational in 2027.")

    deadline_fields = [
        (claim["event_type"], claim["qualifier"], claim["precision"]) for claim in deadline
    ]
    assert deadline_fields == [("operational_target", "deadline", "year")]
    assert [(claim["event_type"], claim["qualifier"], claim["precision"]) for claim in within] == [
        ("operational_target", "within", "year")
    ]


def test_copular_operational_wording_does_not_bind_a_foreign_site_date():
    text = (
        f"{PROJECT} is expected to be operational by 2027, while South Campus "
        "is expected to be operational in 2028."
    )

    claims = scoped(text)

    assert len(claims) == 1
    assert (claims[0]["label"], claims[0]["qualifier"]) == ("2027", "deadline")
