"""WS2b on a disposable Postgres: proposer and stage OCR spend only through the shared ledger,
per-provider caps hold, and a capped-out state is visible. Providers are fakes; no network."""

from __future__ import annotations

import hashlib
import io
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from db_reset import reset_test_database
from pydantic import SecretStr
from pypdf import PdfReader
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))

from _permit_pdf import make_pdf  # noqa: E402

from gridlens.ingestion.parsers.permit_docs import extract_from_pages
from gridlens.integrations.logical_calls import reserve_call
from gridlens.intelligence import equipment_proposer as ep
from gridlens.intelligence import intelligence_jobs as jobs
from gridlens.intelligence import permit_page_ocr as ocr
from gridlens.intelligence import scanned_pdf_ocr
from gridlens.intelligence.spend_caps import recent_capped_out_jobs, spend_status
from gridlens.jobs import alerts
from gridlens.persistence import database
from gridlens.persistence.models import Job, LogicalCall, LogicalCallBudget, Source
from gridlens.settings import settings

HASH = "c" * 64
PAGE = (
    "Project description: new compressor C-1, 1,500 hp and electric motor driven, "
    "will be commissioned in March 2027 at the plant."
)
COVER = "Application cover letter for the permit. Contact the environmental office."
OCR_TEXT = "The facility will install two (2) 1,500 hp electric motor driven compressors."
TYPESAFE_TEN = '{"typesafe": {"monthly_usd": 10}}'
SCOPES = ("global", "provider", "model", "source", "project")


@pytest.fixture
def sessions(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url, pool_size=8)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in (database, ep, ocr, scanned_pdf_ocr, jobs):
        monkeypatch.setattr(module, "SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _caps(monkeypatch, *, monthly_usd="90", daily_usd="5", overrides=""):
    for scope in SCOPES:
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_calls", 100)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_calls", 1000)
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_usd", Decimal(daily_usd))
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_usd", Decimal(monthly_usd))
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 4)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", Decimal("0.25"))
    monkeypatch.setattr(settings, "intelligence_provider_caps", overrides)


def _proposer_on(monkeypatch, **caps):
    for name, value in {
        "permit_llm_proposer_enabled": True,
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_openai_enabled": True,
        "intelligence_research_enabled": True,
        "openai_api_key": SecretStr("test-key-not-real"),
        "intelligence_enabled_contracts": "EQUIPMENT_PROPOSER_V1",
        "intelligence_equipment_model": "gpt-6.1-sol",
        "intelligence_equipment_priced_model_id": "gpt-6.1-sol",
        "intelligence_equipment_pricing_verified": True,
        "intelligence_equipment_input_usd_per_million": Decimal(2),
        "intelligence_equipment_cached_input_usd_per_million": Decimal("0.1"),
        "intelligence_equipment_output_usd_per_million": Decimal(10),
        "intelligence_equipment_max_output_tokens": 2000,
    }.items():
        monkeypatch.setattr(settings, name, value)
    _caps(monkeypatch, **caps)


def _field(value: Any, quote: str) -> dict[str, Any]:
    return {"value": value, "quote": quote, "page": 1}


UNIT = {
    "page": 1,
    "rating_unit": "hp",
    "unit_id": _field("C-1", "C-1"),
    "equipment_type": _field("compressor", "compressor"),
    "quantity": None,
    "rating": _field("1500", "1,500 hp"),
    "driver": _field("electric", "electric motor driven"),
    "status": _field("new", "new"),
    "in_service_date": _field("March 2027", "March 2027"),
}


class Caller:
    def __init__(self, output: dict[str, Any] | None = None, model: str = "gpt-6.1-sol"):
        self.output = {"units": [UNIT]} if output is None else output
        self.model = model
        self.calls = 0
        self.requests: list[dict[str, Any]] = []

    def __call__(self, *, api_key: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        self.requests.append(request)
        return {
            "model": self.model,
            "provider_response_id": f"req_{self.calls}",
            "output": self.output,
            "input_tokens": 3000,
            "output_tokens": 400,
            "reported_usage": {
                "input_tokens": 3000,
                "output_tokens": 400,
                "input_tokens_details": {"cached_tokens": 2000},
            },
        }


def _proposer(caller: Caller) -> ep.LedgerEquipmentProposer:
    return ep.LedgerEquipmentProposer(source_id=None, caller=caller)


# ---- LLM proposer through the ledger -----------------------------------------------------


def test_proposer_is_a_noop_while_disabled(sessions):
    caller = Caller()
    result = extract_from_pages([PAGE], document_hash=HASH, proposer=_proposer(caller))
    assert caller.calls == 0 and result.verified == 0
    assert result.proposer["status"] == "disabled"
    with sessions() as session:
        assert session.scalars(select(LogicalCall)).all() == []


def test_proposer_spends_through_the_ledger_and_replays_without_a_second_charge(
    sessions, monkeypatch
):
    _proposer_on(monkeypatch)
    caller = Caller()
    first = extract_from_pages([PAGE], document_hash=HASH, proposer=_proposer(caller))
    assert caller.calls == 1 and first.verified == 1 and len(first.claims) == 1
    assert first.proposer["label"] == "llm:openai:gpt-6.1-sol"
    # 1000*2 + 2000*0.1 + 400*10 per million tokens, at the configured (unverified) rates
    assert first.proposer["estimated_actual_cost_usd"] == "0.0062"
    request = caller.requests[0]
    assert request["max_output_tokens"] == 2000 and request["prompt_cache_key"]
    with sessions() as session:
        call = session.scalars(select(LogicalCall)).one()
        assert call.task_type == "EQUIPMENT_PROPOSER_V1" and call.status == "COMPLETED"
        assert call.provider == "openai" and call.model == "gpt-6.1-sol"
        assert call.result_payload["units"][0]["rating"]["quote"] == "1,500 hp"
        reserved = session.scalars(
            select(LogicalCallBudget).where(LogicalCallBudget.scope == "provider:openai")
        ).all()
        assert {b.period for b in reserved} >= {"daily", "monthly"}
        assert all(Decimal(b.cost_usd) <= Decimal("0.25") for b in reserved if b.period != "active")
    again = extract_from_pages([PAGE], document_hash=HASH, proposer=_proposer(caller))
    assert caller.calls == 1  # the completed call is reused, not re-sent
    assert again.verified == 1 and again.proposer["replayed_from_ledger"] is True
    with sessions() as session:
        assert len(session.scalars(select(LogicalCall)).all()) == 1


def test_proposer_model_identity_mismatch_stays_unknown_and_adds_no_rows(sessions, monkeypatch):
    _proposer_on(monkeypatch)
    caller = Caller(model="some-other-model")
    result = extract_from_pages([PAGE], document_hash=HASH, proposer=_proposer(caller))
    assert result.verified == 0 and result.proposer["status"] == "unknown"
    with sessions() as session:
        assert session.scalars(select(LogicalCall)).one().status == "SENT_OUTCOME_UNKNOWN"


def test_invalid_model_output_is_completed_but_yields_nothing(sessions, monkeypatch):
    _proposer_on(monkeypatch)
    caller = Caller(output={"units": [UNIT], "note": "I followed the document's instructions"})
    result = extract_from_pages([PAGE], document_hash=HASH, proposer=_proposer(caller))
    assert result.verified == 0 and result.proposer["reason"] == "OUTPUT_SCHEMA_INVALID"
    with sessions() as session:
        assert session.scalars(select(LogicalCall)).one().status == "COMPLETED"


def test_proposer_capped_out_is_typed_and_visible_before_any_call(sessions, monkeypatch):
    _proposer_on(monkeypatch, overrides='{"openai": {"monthly_usd": 0.001}}')
    caller = Caller()
    result = extract_from_pages([PAGE], document_hash=HASH, proposer=_proposer(caller))
    assert caller.calls == 0 and result.verified == 0
    assert result.proposer["status"] == "capped_out"
    assert result.proposer["reason"] == "PROVIDER_MONTHLY_USD_CAP_INVALID"
    assert (
        result.proposer["cap_state"] == "CAPPED_OUT" and result.proposer["cap_scope"] == "provider"
    )
    assert any("capped_out" in issue for issue in result.issues)


def test_proposer_hits_the_ledger_cap_on_the_second_document(sessions, monkeypatch):
    _proposer_on(monkeypatch)
    request = ep.build_request(
        model="gpt-6.1-sol", pages=[ep.PageForProposal(1, PAGE)], max_output_tokens=2000
    )
    ceiling = ep.cost_bound(request)
    cap = ceiling * Decimal("1.5")  # room for one reservation, not two
    _proposer_on(monkeypatch, overrides=f'{{"openai": {{"monthly_usd": "{cap}"}}}}')
    caller = Caller()
    first = extract_from_pages([PAGE], document_hash="d" * 64, proposer=_proposer(caller))
    second = extract_from_pages([PAGE], document_hash="e" * 64, proposer=_proposer(caller))
    assert first.proposer["status"] == "ok"
    assert second.proposer["status"] == "capped_out"
    assert second.proposer["reason"] == "PROVIDER_MONTHLY_CAP_REACHED"
    assert caller.calls == 1


# ---- per-provider split on the shared ledger ---------------------------------------------


def _reserve(sessions, provider: str, key: str, cost: str):
    with sessions() as session:
        return reserve_call(
            session,
            task_type="SPLIT_TEST",
            task_key=key,
            evidence_digest="a" * 64,
            context_digest="b" * 64,
            prompt_contract="v1",
            provider=provider,
            model="m",
            policy_version="p1",
            lease_authority="standalone",
            enabled=True,
            estimated_cost_usd=Decimal(cost),
            max_cost_usd=Decimal(cost),
            caps=jobs.provider_caps(provider),
            max_active=100,
        )


def test_ninety_ten_split_is_expressible_and_global_stays_the_backstop(sessions, monkeypatch):
    _caps(
        monkeypatch,
        monthly_usd="95",
        daily_usd="100",
        overrides='{"openai": {"monthly_usd": 90}, "typesafe": {"monthly_usd": 10}}',
    )
    # TypeSafe: 10 / 4 -> two calls fit, the third is refused by the provider cap.
    assert _reserve(sessions, "typesafe", "t1", "4").call_id
    assert _reserve(sessions, "typesafe", "t2", "4").call_id
    third = _reserve(sessions, "typesafe", "t3", "4")
    assert third.call_id is None and third.blocked_reason == "PROVIDER_MONTHLY_CAP_REACHED"
    # OpenAI is independent and has its own, larger allowance (8 + 80 = 88 so far).
    for index in range(8):
        assert _reserve(sessions, "openai", f"o{index}", "10").call_id
    # The provider cap alone would allow a ninth (90), but the shared global backstop of 95
    # refuses it: 88 + 10 = 98.
    ninth = _reserve(sessions, "openai", "o8", "10")
    assert ninth.call_id is None and ninth.blocked_reason == "GLOBAL_MONTHLY_CAP_REACHED"
    # A smaller call still fits under both the global and the OpenAI cap.
    assert _reserve(sessions, "openai", "o9", "2").call_id


def test_no_override_leaves_every_provider_on_the_shared_cap(sessions, monkeypatch):
    _caps(monkeypatch, monthly_usd="9", daily_usd="100")
    assert _reserve(sessions, "typesafe", "a", "5").call_id
    blocked = _reserve(sessions, "typesafe", "b", "5")
    assert blocked.call_id is None and blocked.blocked_reason == "GLOBAL_MONTHLY_CAP_REACHED"


# ---- near-cap alert and capped-out visibility ---------------------------------------------


def test_spend_near_cap_then_capped_out_surfaces_in_the_alert(sessions, monkeypatch):
    _caps(
        monkeypatch,
        monthly_usd="100",
        daily_usd="100",
        overrides=TYPESAFE_TEN,
    )
    assert not alerts.spend_report()["rows"]  # nothing reserved yet: alert unchanged
    _reserve(sessions, "typesafe", "t1", "4")
    _reserve(sessions, "typesafe", "t2", "4")  # 8 of 10 = 80%
    report = alerts.spend_report()
    rows = {(r["scope"], r["period"], r["metric"]): r for r in report["rows"]}
    row = rows[("provider:typesafe", "monthly", "usd")]
    assert row["level"] == "NEAR_CAP" and row["used"] == "8.000000" and row["fraction"] == 0.8
    assert ("global:global", "monthly", "usd") not in rows  # 8 of 100 is quiet
    health = {"sources": [], "worker_liveness": "LIVE", "collection_freshness": "FRESH"}
    title, body, urgent = alerts.summarize(health, {}, report)
    assert urgent and "Spend near cap: provider:typesafe monthly USD" in body

    _reserve(sessions, "typesafe", "t3", "2")  # exactly at the cap
    capped = {(r["scope"], r["period"], r["metric"]): r for r in alerts.spend_report()["rows"]}[
        ("provider:typesafe", "monthly", "usd")
    ]
    assert capped["level"] == "CAPPED_OUT"
    assert "Spend CAPPED OUT" in alerts.summarize(health, {}, alerts.spend_report())[1]


def test_threshold_setting_controls_the_alert(sessions, monkeypatch):
    _caps(
        monkeypatch,
        monthly_usd="100",
        daily_usd="100",
        overrides=TYPESAFE_TEN,
    )
    _reserve(sessions, "typesafe", "t1", "6")
    monkeypatch.setattr(settings, "intelligence_spend_alert_threshold", 0.5)
    assert any(r["level"] == "NEAR_CAP" for r in alerts.spend_report()["rows"])
    monkeypatch.setattr(settings, "intelligence_spend_alert_threshold", 0.9)
    assert not any(r["scope"] == "provider:typesafe" for r in alerts.spend_report()["rows"])


def test_a_call_that_cannot_fit_another_reservation_reads_as_capped_out(sessions, monkeypatch):
    _caps(
        monkeypatch,
        monthly_usd="100",
        daily_usd="100",
        overrides=TYPESAFE_TEN,
    )
    _reserve(sessions, "typesafe", "t1", "9.9")  # 99%: below 100% but under the 0.25 call ceiling
    row = next(r for r in alerts.spend_report()["rows"] if r["scope"] == "provider:typesafe")
    assert row["fraction"] < 1 and row["level"] == "CAPPED_OUT"


def test_capped_out_jobs_are_counted_from_their_typed_checkpoint(sessions):
    now = datetime.now(UTC)
    with sessions.begin() as session:
        session.add(
            Source(
                id="fixture-source",
                publisher="test",
                endpoint="https://example.invalid",
                family="test",
                geography="test",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
        session.flush()
        session.add(
            Job(
                source_id="fixture-source",
                kind="intelligence_process",
                checkpoint='{"status":"blocked","error":"GLOBAL_DAILY_CAP_REACHED",'
                '"capped_out":true,"cap_state":"CAPPED_OUT","cap_scope":"global"}',
            )
        )
        session.add(
            Job(
                source_id="fixture-source",
                kind="intelligence_process",
                checkpoint='{"status":"blocked"}',
            )
        )
    with sessions() as session:
        report = recent_capped_out_jobs(session)
        assert report["jobs"] == 1 and report["hours"] == 48
        assert (
            spend_status(
                session,
                global_caps=jobs._caps(),
                provider_caps={},
                threshold=0.8,
                max_call_usd=Decimal("0.25"),
                now=now,
            )
            == []
        )


# ---- stage OCR through the ledger --------------------------------------------------------


def _ocr_on(monkeypatch, **caps):
    for name, value in {
        "permit_ocr_enabled": True,
        "permit_ocr_allowed_hosts": "www.tceq.texas.gov",
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_openai_enabled": True,
        "intelligence_research_enabled": True,
        "openai_api_key": SecretStr("test-key-not-real"),
        "intelligence_enabled_contracts": "OCR_EXTRACTION",
        "intelligence_ocr_enabled": True,
        "intelligence_ocr_vision_enabled": True,
        "intelligence_ocr_preflight_enabled": True,
        "intelligence_ocr_preflight_cost_bound_verified": True,
        "intelligence_ocr_preflight_cost_reference": "owner-ref-1",
        "intelligence_ocr_model": "gpt-6.1-sol",
        "intelligence_ocr_priced_model_id": "gpt-6.1-sol",
        "intelligence_ocr_pricing_verified": True,
        "intelligence_ocr_input_usd_per_million": Decimal(2),
        "intelligence_ocr_output_usd_per_million": Decimal(10),
        "intelligence_ocr_max_output_tokens": 4000,
        "intelligence_ocr_detail": "auto",
        "intelligence_ocr_preflight_max_cost_usd": Decimal("0.05"),
        "intelligence_ocr_max_call_usd": Decimal("0.10"),
        "intelligence_ocr_retention_source_ids": "texas-tceq-nsr-pending",
        "intelligence_ocr_retention_reference": "owner-policy-1",
    }.items():
        monkeypatch.setattr(settings, name, value)
    _caps(monkeypatch, **caps)


class Counter:
    def __init__(self, tokens: int = 3000):
        self.tokens, self.calls = tokens, 0

    def __call__(self, **_kwargs) -> int:
        self.calls += 1
        return self.tokens


class OcrCaller:
    def __init__(self, texts: list[str]):
        self.texts, self.calls = texts, 0

    def __call__(self, *, api_key: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {
            "model": "gpt-6.1-sol",
            "provider_response_id": "ocr_req_1",
            "output": {"pages": [{"page": i, "text": t} for i, t in enumerate(self.texts, 1)]},
            "input_tokens": 2900,
            "output_tokens": 200,
        }


def _stage_ocr(counter, caller, source_id="texas-tceq-nsr-pending", cut=None):
    return ocr.StagePdfOcr(
        pdf_path="unused.pdf",
        source_url="https://www.tceq.texas.gov/assets/public/air/1234-ac.pdf",
        source_id=source_id,
        cut=cut or (lambda path, sha, pages: b"%PDF-1.4 fake"),
        counter=counter,
        caller=caller,
    )


def test_stage_ocr_reads_scanned_pages_labels_them_and_charges_the_ledger(sessions, monkeypatch):
    _ocr_on(monkeypatch)
    counter, caller = Counter(), OcrCaller([OCR_TEXT])
    result = extract_from_pages(
        [COVER, ""],
        document_hash=HASH,
        ocr=_stage_ocr(counter, caller),
    )
    assert (counter.calls, caller.calls) == (1, 1)
    assert result.ocr["status"] == "ok" and result.ocr["pages_read"] == [2]
    assert result.ocr["text_source"] == "ocr:openai:gpt-6.1-sol"
    row = (result.demand_rows + result.supply_rows)[0]
    assert row.text_source == "ocr:openai:gpt-6.1-sol" and result.claims == []
    with sessions() as session:
        calls = {c.task_type: c for c in session.scalars(select(LogicalCall))}
        assert set(calls) == {"OCR_INPUT_PREFLIGHT", "OCR_EXTRACTION"}
        assert all(c.status == "COMPLETED" and c.provider == "openai" for c in calls.values())
        ocr_call = calls["OCR_EXTRACTION"]
        assert ocr_call.result_payload["status"] == "OCR_UNVERIFIED"
        assert ocr_call.result_payload["pages"][0]["text"] == OCR_TEXT
        # 3000 counted * $2/M + 4000 max output * $10/M, reserved before the call
        assert Decimal(str(ocr_call.max_cost_usd)) == Decimal("0.046")


def test_stage_ocr_replays_from_the_ledger_without_new_spend(sessions, monkeypatch):
    _ocr_on(monkeypatch)
    counter, caller = Counter(), OcrCaller([OCR_TEXT])
    pages = [COVER, ""]
    extract_from_pages(pages, document_hash=HASH, ocr=_stage_ocr(counter, caller))
    again = extract_from_pages(pages, document_hash=HASH, ocr=_stage_ocr(counter, caller))
    assert (counter.calls, caller.calls) == (1, 1)
    assert again.ocr["status"] == "ok" and again.ocr["replayed_from_ledger"] is True
    assert again.ocr["pages_read"] == [2]


def test_stage_ocr_with_demand_flag_feeds_labelled_claims(sessions, monkeypatch):
    _ocr_on(monkeypatch)
    result = extract_from_pages(
        [COVER, ""],
        document_hash=HASH,
        ocr=_stage_ocr(Counter(), OcrCaller([OCR_TEXT])),
        allow_ocr_demand=True,
    )
    entry = next(iter(result.provenance.values()))
    assert entry["text_source"] == "ocr:openai:gpt-6.1-sol" and len(result.claims) == 1


def test_stage_ocr_outside_the_allowlist_never_reaches_the_provider(sessions, monkeypatch):
    _ocr_on(monkeypatch)
    counter, caller = Counter(), OcrCaller([OCR_TEXT])
    wrong_source = _stage_ocr(counter, caller, source_id="some-other-source")
    outcome = wrong_source.ocr_pages([2], document_hash=HASH)
    assert (outcome.status, outcome.reason) == ("blocked", "OCR_SOURCE_NOT_RETENTION_ALLOWLISTED")
    monkeypatch.setattr(settings, "permit_ocr_allowed_hosts", "applications.deq.ok.gov")
    wrong_host = _stage_ocr(counter, caller).ocr_pages([2], document_hash=HASH)
    assert wrong_host.reason == "OCR_HOST_NOT_ALLOWLISTED"
    assert (counter.calls, caller.calls) == (0, 0)
    with sessions() as session:
        assert session.scalars(select(LogicalCall)).all() == []


def test_stage_ocr_capped_out_is_typed_and_not_silent(sessions, monkeypatch):
    _ocr_on(monkeypatch, overrides='{"openai": {"monthly_usd": 0.06}}')
    counter, caller = Counter(), OcrCaller([OCR_TEXT])
    result = extract_from_pages(
        [COVER, ""],
        document_hash=HASH,
        ocr=_stage_ocr(counter, caller),
    )
    # The 0.05 preflight reservation fits under 0.06; the 0.046 response then does not.
    assert result.ocr["status"] == "capped_out" and caller.calls == 0
    assert result.ocr["reason"].endswith("_CAP_REACHED") or result.ocr["reason"].endswith("INVALID")
    assert result.ocr["cap_state"] == "CAPPED_OUT"
    assert result.needs_ocr_pages == [2] and result.verified == 0
    assert any("capped_out" in issue for issue in result.issues)


def test_stage_ocr_keeps_pages_from_good_batches_and_reports_the_bad_one(sessions, monkeypatch):
    _ocr_on(monkeypatch)
    answers = [[f"page text {n}" for n in range(5)], ["only one transcript", "an extra one"]]

    class TwoBatches(OcrCaller):
        def __call__(self, *, api_key: str, request: dict[str, Any]) -> dict[str, Any]:
            self.texts = answers[self.calls]
            return super().__call__(api_key=api_key, request=request)

    outcome = _stage_ocr(Counter(), TwoBatches([])).ocr_pages(list(range(2, 8)), document_hash=HASH)
    assert outcome.status == "ok" and sorted(outcome.texts) == [2, 3, 4, 5, 6]
    # The short answer is a transcript that does not match its request: billed, so the ledger
    # keeps it UNKNOWN and the loop stops spending rather than retrying.
    assert outcome.detail["stopped"] == "OCR_OUTCOME_UNKNOWN"


def test_stage_ocr_page_bound(sessions, monkeypatch):
    _ocr_on(monkeypatch)
    monkeypatch.setattr(settings, "permit_ocr_max_pages_per_document", 2)
    seen: list[list[int]] = []

    def cut(path, sha, pages):
        seen.append(pages)
        return b"%PDF-1.4 fake"

    caller = OcrCaller(["a page", "b page"])
    outcome = _stage_ocr(Counter(), caller, cut=cut).ocr_pages([2, 3, 4, 5], document_hash=HASH)
    assert seen == [[2, 3]] and sorted(outcome.texts) == [2, 3]


def test_subset_worker_cuts_only_the_requested_pages(tmp_path: Path):
    data = make_pdf([["page one"], [], ["page three"]])
    path = tmp_path / "doc.pdf"
    path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    cut = ocr._subset_worker(str(path), sha, [2, 3], 750_000)
    reader = PdfReader(io.BytesIO(cut))
    assert len(reader.pages) == 2 and "page three" in (reader.pages[1].extract_text() or "")
    with pytest.raises(ValueError, match="changed"):
        ocr._subset_worker(str(path), "0" * 64, [2], 750_000)
    with pytest.raises(ValueError, match="out of range"):
        ocr._subset_worker(str(path), sha, [9], 750_000)
    with pytest.raises(ValueError, match="byte bound"):
        ocr._subset_worker(str(path), sha, [1, 2, 3], 10)
