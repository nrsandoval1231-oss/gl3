"""Refused dispatch releases the reservation in every provider-call module (no Postgres)."""

from __future__ import annotations

import re
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from gridlens.ingestion.parsers.permit_docs.proposals import PageForProposal
from gridlens.integrations.logical_calls import ReservationResult
from gridlens.intelligence import equipment_proposer as ep
from gridlens.intelligence import intelligence_jobs as jobs

SRC = Path(jobs.__file__).parent


@pytest.fixture
def cancelled(monkeypatch):
    calls: list[tuple[object, int]] = []

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(jobs, "SessionLocal", fake_session)
    monkeypatch.setattr(
        jobs,
        "cancel_call",
        lambda _s, call_id, *, fence_token: calls.append((call_id, fence_token)),
    )
    return calls


@pytest.mark.parametrize(
    ("status", "reason", "expect_cancel"),
    [
        ("NOT_SENT", "INTELLIGENCE_DISABLED", True),
        ("NOT_SENT", "STALE_FENCE", True),
        ("BLOCKED", "PROVIDER_BILLING_QUARANTINED", True),
        ("SENT_OUTCOME_UNKNOWN", "ALREADY_DISPATCHED_OR_TERMINAL", False),
        ("COMPLETED", "ALREADY_DISPATCHED_OR_TERMINAL", False),
        ("CANCELLED", "ALREADY_DISPATCHED_OR_TERMINAL", False),
    ],
)
def test_release_only_unsent_calls(cancelled, status, reason, expect_cancel):
    call_id = uuid4()
    jobs.release_undispatched_call(call_id, 5, ReservationResult(call_id, False, status, reason))
    assert cancelled == ([(call_id, 5)] if expect_cancel else [])


@pytest.mark.parametrize(
    ("status", "reason"),
    [("BLOCKED", "PROVIDER_BILLING_QUARANTINED"), ("NOT_SENT", "INTELLIGENCE_DISABLED")],
)
def test_equipment_proposer_cancels_before_reporting_blocked(
    cancelled, monkeypatch, status, reason
):
    call_id = uuid4()
    monkeypatch.setattr(ep, "proposer_enabled", lambda: (True, "openai", "m", ""))
    monkeypatch.setattr(ep, "build_request", lambda **_: {"input": "x"})
    monkeypatch.setattr(ep, "cost_bound", lambda _r: Decimal("0.01"))
    monkeypatch.setattr(jobs, "_dispatch_policy", lambda *a, **k: (True, ""))
    monkeypatch.setattr(jobs, "provider_caps", lambda _p: {})

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(ep, "SessionLocal", fake_session)
    monkeypatch.setattr(
        ep, "reserve_call", lambda *_a, **_k: ReservationResult(call_id, False, "NOT_SENT", None, 9)
    )
    monkeypatch.setattr(
        ep,
        "mark_dispatched",
        lambda *_a, **_k: ReservationResult(call_id, False, status, reason, 9),
    )
    proposer = ep.LedgerEquipmentProposer(
        source_id=None, project_id=None, job_id=None, worker_id=None, fence_token=3
    )
    out = proposer.propose([PageForProposal(1, "Compressor C-1 1,500 hp")], document_hash="a" * 64)
    assert out.status == "blocked" and out.reason == reason
    assert cancelled == [(call_id, 9)]


@pytest.mark.parametrize(
    "module", ["intelligence_jobs", "scanned_pdf_ocr", "permit_page_ocr", "equipment_proposer"]
)
def test_every_dispatch_refusal_site_releases_the_reservation(module):
    text = (SRC / f"{module}.py").read_text()
    dispatches = len(re.findall(r"= mark_dispatched\(", text))
    releases = len(re.findall(r"release_undispatched_call\(", text)) - (
        1 if module == "intelligence_jobs" else 0  # the definition itself
    )
    assert dispatches > 0 and releases >= dispatches
