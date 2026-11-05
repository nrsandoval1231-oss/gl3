from __future__ import annotations

import pytest

from gridlens.ingestion.adapters.puct_ccn_extract import merge_fields, text_fields


@pytest.mark.parametrize("reverse", [False, True])
def test_document_order_cannot_hide_conflicting_customer_load_quotes(reverse: bool) -> None:
    documented = text_fields(["A customer has submitted a request for 10 MW of load."])
    conflicting = text_fields(
        [
            "A customer has submitted a request for 10 MW of load. "
            "A customer has requested 20 MW of load capacity."
        ]
    )
    parts = [documented, conflicting]
    if reverse:
        parts.reverse()

    request = merge_fields(*parts)["customer_request_mw"]

    assert request["value"] is None
    assert request["basis"] == "unknown"
    assert request["reason"] == "conflicting_statements"
    assert {candidate["value"] for candidate in request["candidates"]} == {10, 20}
    assert all(candidate.get("quote") for candidate in request["candidates"])
