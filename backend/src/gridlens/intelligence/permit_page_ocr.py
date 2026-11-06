"""OCR for scanned pages of permit-stage PDFs, through the shared call ledger.

``scanned_pdf_ocr`` accepts only GovInfo Federal Register PDFs held as Evidence captures.
The TCEQ and Oklahoma DEQ stages hold their PDFs on disk for the length of one run, so this
sibling takes the same ledger, preflight, cap and retention guards to those PDFs without
touching the GovInfo path:

- the PDF's host must be in ``PERMIT_OCR_ALLOWED_HOSTS`` and in a code-level ceiling
  (``HOST_CEILING``), and its source id must be in ``INTELLIGENCE_OCR_RETENTION_SOURCE_IDS``
  with a retention reference;
- only the scanned pages are cut into a sub-PDF in a killable child process, at most five
  pages and ``MAX_PDF_BYTES`` per request, and at most ``PERMIT_OCR_MAX_PAGES_PER_DOCUMENT``
  pages per document;
- each request is counted first (preflight) and reserved at the counted cost, so the
  per-call, global, provider, model, source and project caps all apply;
- the returned text is labelled ``ocr:openai:<model>`` and is OCR_UNVERIFIED: rows read from
  it keep that label in provenance and are retained, not fed to demand, unless
  ``PERMIT_OCR_ROWS_FEED_DEMAND`` is set. The transcript is stored in the ledger result only
  (bounded), exactly like the GovInfo path, and nowhere else.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from gridlens.ingestion.adapters.bounded_http import AcquisitionFailure, run_isolated
from gridlens.ingestion.adapters.govinfo_scan import MAX_PDF_BYTES, MAX_PDF_PAGES
from gridlens.ingestion.parsers.permit_docs.proposals import OcrOutcome
from gridlens.integrations.intelligence_provider import (
    ProviderResponseError,
    call_openai_input_token_count,
    call_openai_request,
    ocr_request_payload,
)
from gridlens.integrations.logical_calls import (
    complete_call,
    fail_call,
    mark_dispatched,
    reserve_call,
)
from gridlens.intelligence.ocr_public_pages import (
    PageApprovalRequired,
    approved_source_pages,
    render_page_images,
    require_page_approval,
)
from gridlens.intelligence.provider_cost_bounds import openai_cost_ceiling_from_tokens
from gridlens.intelligence.scanned_pdf_ocr import (
    OCR_INPUT_WRITE_USD_PER_MILLION,
    OCR_MAX_CALL_USD,
    OCR_OUTPUT_USD_PER_MILLION,
    OCR_POLICY_VERSION,
    OCR_PREFLIGHT_CONTRACT_VERSION,
    OCR_SCHEMA_VERSION,
    OCR_TASK,
    _digest,
    _ledger_caps,
    _ocr_configuration_ready,
    _ocr_response_ready,
    _preflight_context_digest,
    _preflight_ready,
    _quarantine_ocr_response,
    _retention_source_ids,
    _validate_ocr_response_usage,
)
from gridlens.intelligence.spend_caps import cap_fields
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import LogicalCall
from gridlens.settings import settings

PREFLIGHT_TASK = "OCR_INPUT_PREFLIGHT"
# Code-level ceiling: configuration may narrow this list but never extend it.
HOST_CEILING = frozenset({"www.govinfo.gov", "www.tceq.texas.gov", "applications.deq.ok.gov"})
MAX_PAGE_TEXT_CHARS = 20_000
# JSON-encoded (ensure_ascii) size of the stored transcript, kept under the 65,536-byte public
# transcript bound with a margin; escapes can expand non-ASCII text up to six times.
MAX_TRANSCRIPT_JSON_BYTES = 60_000
MAX_SOURCE_PDF_BYTES = 130 * 1024 * 1024
SUBSET_DEADLINE_SECONDS = 30.0


def allowed_hosts() -> set[str]:
    configured = {h.strip().lower() for h in settings.permit_ocr_allowed_hosts.split(",") if h}
    return {h for h in configured if h in HOST_CEILING}


def ocr_label(model: str) -> str:
    """The ``text_source`` carried in provenance for pages read by this OCR provider."""
    return f"ocr:openai:{model}"


def stage_pdf_allowed(source_url: str, source_id: str) -> tuple[bool, str]:
    parts = urlsplit(source_url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or parts.fragment
        or len(source_url) > 500
    ):
        return False, "OCR_URL_NOT_ALLOWED"
    if parts.hostname.lower() not in allowed_hosts():
        return False, "OCR_HOST_NOT_ALLOWLISTED"
    if source_id not in _retention_source_ids():
        return False, "OCR_SOURCE_NOT_RETENTION_ALLOWLISTED"
    if not settings.intelligence_ocr_retention_reference.strip():
        return False, "OCR_RETENTION_REFERENCE_MISSING"
    return True, ""


def stage_ocr_ready() -> tuple[bool, str]:
    if not settings.permit_ocr_enabled:
        return False, "PERMIT_OCR_SETTING_OFF"
    return _ocr_configuration_ready()


def _subset_worker(path: str, expected_sha256: str, pages: list[int], max_bytes: int) -> bytes:
    """Child process: verify the file, then write only the requested pages as a new PDF."""
    from pypdf import PdfReader, PdfWriter

    if os.path.getsize(path) > MAX_SOURCE_PDF_BYTES:
        raise ValueError("source PDF exceeds the size bound")
    with open(path, "rb") as handle:
        data = handle.read()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("source PDF changed")
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise ValueError("source PDF is encrypted")
    writer = PdfWriter()
    for number in pages:
        if not 1 <= number <= len(reader.pages):
            raise ValueError("page out of range")
        writer.add_page(reader.pages[number - 1])
    out = io.BytesIO()
    writer.write(out)
    result = out.getvalue()
    if len(result) > max_bytes:
        raise ValueError("page subset exceeds the byte bound")
    return result


def cut_pages(path: str, document_hash: str, pages: list[int]) -> bytes:
    deadline = time.monotonic() + SUBSET_DEADLINE_SECONDS
    result: bytes = run_isolated(
        "gridlens.intelligence.permit_page_ocr:_subset_worker",
        (path, document_hash, pages, MAX_PDF_BYTES),
        {},
        deadline=deadline,
    )
    return result


def _batches(pages: list[int]) -> list[list[int]]:
    return [pages[i : i + MAX_PDF_PAGES] for i in range(0, len(pages), MAX_PDF_PAGES)]


class TranscriptRejected(ValueError):
    """The provider answered, but its transcript fails a local limit."""


class StagePdfOcr:
    """``PageOcr`` for one stage PDF on disk. Spends only through the shared ledger."""

    def __init__(
        self,
        *,
        pdf_path: str,
        source_url: str,
        source_id: str,
        project_id: UUID | None = None,
        job_id: UUID | None = None,
        worker_id: str | None = None,
        fence_token: int = 0,
        cut: Callable[[str, str, list[int]], bytes] = cut_pages,
        counter: Callable[..., int] = call_openai_input_token_count,
        caller: Callable[..., dict[str, Any]] = call_openai_request,
    ) -> None:
        self.pdf_path = pdf_path
        self.source_url = source_url
        self.source_id = source_id
        self.project_id = project_id
        self.job_id = job_id
        self.worker_id = worker_id
        self.fence_token = fence_token
        self.cut = cut
        self.counter = counter
        self.caller = caller

    def ocr_pages(self, pages: list[int], *, document_hash: str) -> OcrOutcome:
        ready, reason = stage_ocr_ready()
        if not ready:
            return OcrOutcome("disabled", reason)
        allowed, reason = stage_pdf_allowed(self.source_url, self.source_id)
        if not allowed:
            return OcrOutcome("blocked", reason)
        model = settings.intelligence_ocr_model
        label = ocr_label(model)
        scanned_pages = sorted(set(pages))
        if any(type(page) is not int or page < 1 for page in scanned_pages):
            return OcrOutcome("blocked", "OCR_DOCUMENT_PAGE_LIMIT_EXCEEDED")
        approved = approved_source_pages(
            document_hash,
            scanned_pages,
            settings.intelligence_ocr_reviewed_page_hashes,
        )
        wanted = approved[: settings.permit_ocr_max_pages_per_document]
        not_selected = sorted(set(scanned_pages) - set(wanted))
        if not wanted:
            return OcrOutcome(
                "blocked",
                "OCR_PAGE_REVIEW_REQUIRED",
                detail={"pages_not_reviewed": not_selected},
            )
        texts: dict[int, str] = {}
        failed: dict[str, str] = {}
        stop: OcrOutcome | None = None
        replayed = False
        for batch in _batches(wanted):
            try:
                sub_pdf = self.cut(self.pdf_path, document_hash, batch)
            except (AcquisitionFailure, ValueError, OSError, TimeoutError) as exc:
                failed[",".join(map(str, batch))] = type(exc).__name__
                continue
            outcome = self._ocr_batch(sub_pdf, batch, document_hash, model)
            if outcome.status == "ok":
                texts.update(outcome.texts)
                replayed = replayed or bool(outcome.detail.get("replayed_from_ledger"))
                continue
            if outcome.status in {"capped_out", "blocked", "unknown"}:
                stop = outcome  # later batches would meet the same wall; stop spending
                break
            failed[",".join(map(str, batch))] = outcome.reason
        detail: dict[str, Any] = {
            "pages_failed": failed,
            "pages_not_reviewed_or_over_limit": not_selected,
        }
        if replayed:
            detail["replayed_from_ledger"] = True
        if stop is not None:
            detail.update(stop.detail)
            detail["stopped"] = stop.reason
        if texts:
            return OcrOutcome("ok", "", texts, label, detail)
        if stop is not None:
            return OcrOutcome(stop.status, stop.reason, {}, label, detail)
        return OcrOutcome("failed", "OCR_NO_PAGES_READ", {}, label, detail)

    def _reserve(
        self,
        *,
        task_type: str,
        task_key: str,
        document_hash: str,
        context_digest: str,
        model: str,
        cost: Decimal,
        prompt_contract: str,
    ) -> Any:
        with SessionLocal() as session:
            return reserve_call(
                session,
                task_type=task_type,
                task_key=task_key,
                evidence_digest=document_hash,
                context_digest=context_digest,
                prompt_contract=prompt_contract,
                provider="openai",
                model=model,
                policy_version=OCR_POLICY_VERSION,
                source_id=self.source_id,
                project_id=self.project_id,
                lease_authority="job" if self.job_id is not None else "standalone",
                job_id=self.job_id,
                worker_id=self.worker_id,
                enabled=True,
                estimated_cost_usd=cost,
                max_cost_usd=cost,
                caps=_ledger_caps(),
                max_active=settings.intelligence_max_active_calls,
                fence_token=self.fence_token,
            )

    @staticmethod
    def _stop(status: str, reason: str) -> OcrOutcome:
        typed = cap_fields(reason)
        return OcrOutcome("capped_out" if typed else status, reason, {}, "", dict(typed))

    def _ocr_batch(
        self, sub_pdf: bytes, batch: list[int], document_hash: str, model: str
    ) -> OcrOutcome:
        detail = settings.intelligence_ocr_detail
        try:
            page_images = render_page_images(
                sub_pdf,
                local_pages=list(range(1, len(batch) + 1)),
                source_pages=batch,
            )
            require_page_approval(
                document_hash,
                page_images,
                settings.intelligence_ocr_reviewed_page_hashes,
            )
        except PageApprovalRequired:
            return OcrOutcome("blocked", "OCR_PAGE_REVIEW_REQUIRED")
        except (AcquisitionFailure, ValueError, TimeoutError):
            return OcrOutcome("failed", "OCR_PAGE_RENDER_FAILED")
        request = ocr_request_payload(
            model=model,
            page_images=page_images,
            detail=detail,
            max_output_tokens=settings.intelligence_ocr_max_output_tokens,
        )
        count_body = {
            k: request[k]
            for k in ("model", "input", "instructions", "text", "tools")
            if k in request
        }
        count_body_digest = _digest(count_body)
        count_context = _preflight_context_digest(model, count_body_digest)
        pages_key = ",".join(map(str, batch))
        preflight_cost = settings.intelligence_ocr_preflight_max_cost_usd
        if not _preflight_ready(preflight_cost):
            return self._stop("blocked", "OCR_PREFLIGHT_FINITE_BUDGET_REQUIRED")
        count_res = self._reserve(
            task_type=PREFLIGHT_TASK,
            task_key=f"{document_hash}:{pages_key}:input-count",
            document_hash=document_hash,
            context_digest=count_context,
            model=model,
            cost=preflight_cost,
            prompt_contract=OCR_SCHEMA_VERSION,
        )
        if count_res.call_id is None or count_res.blocked_reason:
            return self._stop("blocked", count_res.blocked_reason or "PREFLIGHT_RESERVATION_FAILED")
        fence = count_res.fence_token or self.fence_token
        if count_res.status == "SENT_OUTCOME_UNKNOWN":
            return self._stop("unknown", "PREFLIGHT_OUTCOME_UNKNOWN")
        if count_res.status == "FAILED":
            return OcrOutcome("failed", "PREFLIGHT_FAILED")
        if count_res.status == "COMPLETED":
            with SessionLocal() as session:
                row = session.get(LogicalCall, count_res.call_id)
                stored = row.result_payload if row is not None else None
            counted = stored.get("counted_input_tokens") if isinstance(stored, dict) else None
            if (
                not isinstance(stored, dict)
                or stored.get("count_body_digest") != count_body_digest
                or type(counted) is not int
                or counted <= 0
            ):
                return OcrOutcome("failed", "PREFLIGHT_REQUEST_MISMATCH")
        else:
            with SessionLocal() as session:
                sent = mark_dispatched(
                    session,
                    count_res.call_id,
                    fence_token=fence,
                    enabled=_preflight_ready(preflight_cost),  # policy re-checked at dispatch
                )
            if sent.status != "SENT_OUTCOME_UNKNOWN" or sent.blocked_reason:
                return self._stop("blocked", sent.blocked_reason or "PREFLIGHT_NOT_DISPATCHED")
            try:
                key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
                counted = self.counter(api_key=key, model=model, response_request=request)
                payload = {
                    "purpose": "preflight_only",
                    "counted_input_tokens": counted,
                    "count_body_digest": count_body_digest,
                    "count_context_digest": count_context,
                    "model": model,
                    "contract_version": OCR_PREFLIGHT_CONTRACT_VERSION,
                    "counted_input_tokens_are_billable_usage": False,
                    "actual_cost_usd": "0",
                }
                with SessionLocal() as session:
                    complete_call(
                        session,
                        count_res.call_id,
                        fence_token=fence,
                        actual_cost_usd=Decimal("0"),
                        result_digest=_digest(payload),
                        result_payload=payload,
                    )
            except Exception as exc:  # noqa: BLE001 - classify, never retry blind
                return self._classify_failure(exc, count_res.call_id, fence, "count")
        response_cost = openai_cost_ceiling_from_tokens(
            counted,
            settings.intelligence_ocr_max_output_tokens,
            input_rate_usd_per_million=OCR_INPUT_WRITE_USD_PER_MILLION,
            output_rate_usd_per_million=OCR_OUTPUT_USD_PER_MILLION,
        )
        if (
            response_cost <= 0
            or response_cost > OCR_MAX_CALL_USD
            or response_cost > settings.intelligence_ocr_max_call_usd
        ):
            return self._stop("blocked", "OCR_RESPONSE_FINITE_BUDGET_REQUIRED")
        res = self._reserve(
            task_type=OCR_TASK,
            task_key=f"{document_hash}:{pages_key}:ocr",
            document_hash=document_hash,
            context_digest=_digest(
                {
                    "request": _digest(request),
                    "count_call_id": str(count_res.call_id),
                    "counted_input_tokens": counted,
                }
            ),
            model=model,
            cost=response_cost,
            prompt_contract=OCR_SCHEMA_VERSION,
        )
        if res.call_id is None or res.blocked_reason:
            return self._stop("blocked", res.blocked_reason or "OCR_RESERVATION_FAILED")
        fence = res.fence_token or self.fence_token
        if res.status == "COMPLETED":
            return self._from_stored(res.call_id, batch)
        if res.status == "SENT_OUTCOME_UNKNOWN":
            return self._stop("unknown", "OCR_OUTCOME_UNKNOWN")
        if res.status == "FAILED":
            return OcrOutcome("failed", "OCR_CALL_FAILED")
        with SessionLocal() as session:
            sent = mark_dispatched(
                session,
                res.call_id,
                fence_token=fence,
                enabled=_ocr_response_ready(model, detail, response_cost),
            )
        if sent.status != "SENT_OUTCOME_UNKNOWN" or sent.blocked_reason:
            return self._stop("blocked", sent.blocked_reason or "OCR_NOT_DISPATCHED")
        response: dict[str, Any] = {}
        try:
            key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
            response = self.caller(api_key=key, request=request)
            if response.get("model") != model:
                raise ValueError("Provider response model does not match the pinned model")
            if response.get("service_tier") not in {None, "default"}:
                raise ValueError("OCR response used a non-default service tier")
            _validate_ocr_response_usage(
                response,
                counted_input_tokens=counted,
                max_output_tokens=settings.intelligence_ocr_max_output_tokens,
            )
            texts = self._parse_pages(response.get("output"), batch)
            stored = {
                "schema_version": OCR_SCHEMA_VERSION,
                "status": "OCR_UNVERIFIED",
                "authority": "ADVISORY_ONLY",
                "model": model,
                # Entries are numbered within this request; source_pages maps them back.
                "source_pages": batch,
                "pages": [
                    {"page": index, "text": texts[page]} for index, page in enumerate(batch, 1)
                ],
                "usage": {
                    "input_tokens": response.get("input_tokens"),
                    "output_tokens": response.get("output_tokens"),
                },
            }
            if (
                len(json.dumps(stored, ensure_ascii=True).encode("utf-8"))
                > MAX_TRANSCRIPT_JSON_BYTES
            ):
                raise TranscriptRejected("OCR transcript exceeds the stored-size bound")
            with SessionLocal() as session:
                complete_call(
                    session,
                    res.call_id,
                    fence_token=fence,
                    input_tokens=response.get("input_tokens"),
                    output_tokens=response.get("output_tokens"),
                    result_digest=_digest(stored),
                    result_payload=stored,
                )
        except TranscriptRejected as exc:
            # A well-formed, correctly billed response that fails our own local limits: a
            # conclusive local rejection. It must not quarantine the provider.
            request_id = response.get("provider_response_id")
            if not request_id:
                return self._stop("unknown", "OCR_OUTCOME_UNKNOWN")
            with SessionLocal() as session:
                fail_call(
                    session,
                    res.call_id,
                    fence_token=fence,
                    blocked_reason=type(exc).__name__,
                    conclusive_response_ref=f"response:{request_id}",
                )
            return OcrOutcome("failed", "OCR_TRANSCRIPT_REJECTED")
        except Exception as exc:  # noqa: BLE001
            if _quarantine_ocr_response(
                call_id=res.call_id,
                fence_token=fence,
                task_type=OCR_TASK,
                model=model,
                error=exc if not response else None,
                response=response or None,
                input_token_limit=counted,
            ):
                return self._stop("unknown", "OCR_OUTCOME_UNKNOWN")
            return self._classify_failure(exc, res.call_id, fence, "response")
        return OcrOutcome("ok", "", texts)

    @staticmethod
    def _parse_pages(output: Any, batch: list[int]) -> dict[int, str]:
        pages = output.get("pages") if isinstance(output, dict) else None
        if not isinstance(pages, list) or len(pages) != len(batch):
            raise TranscriptRejected("OCR transcript page count does not match the request")
        texts: dict[int, str] = {}
        for index, item in enumerate(pages, start=1):
            if (
                not isinstance(item, dict)
                or set(item) != {"page", "text"}
                or item["page"] != index
                or type(item["page"]) is not int
                or not isinstance(item["text"], str)
                or len(item["text"]) > MAX_PAGE_TEXT_CHARS
            ):
                raise TranscriptRejected("OCR transcript entry is invalid")
            texts[batch[index - 1]] = item["text"]
        return texts

    def _from_stored(self, call_id: UUID, batch: list[int]) -> OcrOutcome:
        with SessionLocal() as session:
            row = session.get(LogicalCall, call_id)
            stored = row.result_payload if row is not None else None
        pages = stored.get("pages") if isinstance(stored, dict) else None
        if not isinstance(pages, list):
            return OcrOutcome("failed", "OCR_RESULT_MISSING")
        try:
            texts = self._parse_pages({"pages": pages}, batch)
        except ValueError:
            return OcrOutcome("failed", "OCR_RESULT_INVALID")
        return OcrOutcome("ok", "", texts, detail={"replayed_from_ledger": True})

    def _classify_failure(
        self, exc: Exception, call_id: UUID, fence: int, phase: str
    ) -> OcrOutcome:
        request_id = getattr(exc, "request_id", None)
        if isinstance(exc, ProviderResponseError) and exc.conclusive and request_id:
            with SessionLocal() as session:
                fail_call(
                    session,
                    call_id,
                    fence_token=fence,
                    blocked_reason=type(exc).__name__,
                    conclusive_response_ref=f"{phase}:{request_id}",
                )
            return OcrOutcome("failed", type(exc).__name__)
        return self._stop("unknown", "OCR_OUTCOME_UNKNOWN")


def configured_stage_ocr(
    *,
    pdf_path: str,
    source_url: str,
    source_id: str,
    project_id: UUID | None = None,
    job_id: UUID | None = None,
    worker_id: str | None = None,
    fence_token: int = 0,
) -> StagePdfOcr | None:
    """The OCR object to pass to the permit_docs pipeline, or ``None`` while the setting is off."""
    if not settings.permit_ocr_enabled:
        return None
    return StagePdfOcr(
        pdf_path=pdf_path,
        source_url=source_url,
        source_id=source_id,
        project_id=project_id,
        job_id=job_id,
        worker_id=worker_id,
        fence_token=fence_token,
    )
