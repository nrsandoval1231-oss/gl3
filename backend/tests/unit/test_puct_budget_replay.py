from __future__ import annotations

from types import SimpleNamespace

import pytest

from gridlens.ingestion.adapters import puct_ccn_dockets as puct
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure


class Fetcher:
    def __init__(self, elapsed: list[float]) -> None:
        self.elapsed = elapsed

    def get(self, url: str, **_kwargs):
        self.elapsed[0] += 5
        body = b"%PDF-test" if "/Documents/" in url else b"<html></html>"
        return SimpleNamespace(body=body, sha256="a" * 64)


ITEMS = [
    {
        "item": "1",
        "filed": "2026-01-01",
        "description": "APPLICATION OF AEP TEXAS INC. TO AMEND ITS CCN",
    },
    {"item": "2", "filed": "2026-01-02", "description": "PRELIMINARY ORDER"},
]


def setup_docket(monkeypatch: pytest.MonkeyPatch, elapsed: list[float], budgets: list[float]):
    monkeypatch.setattr(puct, "parse_items", lambda _page, _control: ITEMS)
    monkeypatch.setattr(
        puct,
        "first_pdf",
        lambda _body,
        _control,
        item: f"https://interchange.puc.texas.gov/Documents/58015_{item}_123.PDF",
    )

    def read_pages(_body: bytes, budget: float, _isolate: bool):
        budgets.append(budget)
        elapsed[0] += 40
        return ["No additional fields are stated here."], []

    monkeypatch.setattr(puct.rpg_extract, "read_pdf_pages", read_pages)
    return Fetcher(elapsed), {"state_key": "58015", "case_style_fields": {}, "filings": "2"}


def test_each_puct_pdf_gets_budget_recomputed_after_fetch_and_prior_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elapsed = [0.0]
    budgets: list[float] = []
    fetcher, record = setup_docket(monkeypatch, elapsed, budgets)

    puct.read_docket(
        fetcher,
        record,
        None,
        lambda: max(0.0, 120.0 - elapsed[0] - 15.0),
        False,
    )

    assert budgets == [90.0, 40.0]


def test_puct_pdf_budget_below_minimum_remains_retryable_time_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elapsed = [0.0]
    budgets: list[float] = []
    fetcher, record = setup_docket(monkeypatch, elapsed, budgets)

    with pytest.raises(DocumentFailure) as caught:
        puct.read_docket(fetcher, record, None, lambda: 10.0, False)

    assert caught.value.code == "text_layer_time_budget"
    assert caught.value.retryable
    assert caught.value.budget_limited
    assert budgets == []
