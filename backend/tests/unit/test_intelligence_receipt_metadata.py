from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from gridlens.api.intelligence import _job_view
from gridlens.intelligence.intelligence_jobs import _provider_response_id


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"provider_response_id": "resp_real"}, "resp_real"),
        ({"provider_response_id": ""}, None),
        ({"provider_response_id": "   "}, None),
        ({"provider_response_id": 42}, None),
        ({"provider_response_id": "x" * 257}, None),
        ({"id": "resp_not_explicit"}, None),
        ({}, None),
    ],
)
def test_only_explicit_bounded_provider_response_ids_are_receiptable(payload, expected):
    assert _provider_response_id(payload) == expected


def test_job_view_labels_legacy_receipt_unknown_and_preserves_explicit_receipt():
    job = SimpleNamespace(
        id=uuid4(),
        target_id=uuid4(),
        status="succeeded",
        checkpoint='{"status":"completed","result":{"answer":"old"}}',
        created_at=datetime.now(UTC),
    )
    legacy = _job_view(job)
    assert legacy["validation_outcome"] == "UNKNOWN"
    assert legacy["validation_reason"] is None
    assert legacy["provider_response_id"] is None

    job.checkpoint = (
        '{"status":"completed","validation_outcome":"VALIDATED",'
        '"provider_response_id":"resp_real","result":{"validation_outcome":"VALIDATED"}}'
    )
    current = _job_view(job)
    assert current["validation_outcome"] == "VALIDATED"
    assert current["provider_response_id"] == "resp_real"
