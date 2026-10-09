"""Execute one bounded question with retained-first, fenced evidence acquisition."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from uuid import UUID

from sqlalchemy import select, text

from gridlens.domain.pursuit_research import ACTIVE, blocker_resolved, fingerprint
from gridlens.ingestion.adapters.buying_chain_public import PublicExtractionUnavailable, retrieve
from gridlens.ingestion.adapters.pursuit_acquisition import (
    SUPPORTED_SOURCES,
    ExtractionUnavailable,
    acquire_registered_record,
    discover_urls,
    extract_public_document,
    retrieval_failure,
)
from gridlens.intelligence.buying_chain import enrich_buying_chain
from gridlens.intelligence.commercial_evaluation import (
    evaluate_target,
    evaluate_targets,
    save_evaluations,
)
from gridlens.intelligence.pursuit_questions import RETRY_BACKOFF_HOURS
from gridlens.intelligence.research_evidence import (
    replay_retained_research,
    retain_registered_record,
    retain_research_document,
)
from gridlens.intelligence.research_routing import routing_context, selected_sources
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    PursuitResearchQuestion,
    Source,
)
from gridlens.settings import settings


def current_cards() -> list[dict]:
    # Reuse the existing authoritative projection, including its admission and
    # exact-event grouping. Do not construct a second research-specific evaluator.
    from gridlens.api.app import _commercial_triage_cards

    with SessionLocal() as session:
        return _commercial_triage_cards(session, 50)


def planning_cards() -> list[dict]:
    """Discover active needs and recheck saved targets beyond the UI shortlist.

    This read-only scan performs no acquisitions. Question scheduling separately
    enforces its daily cap, two active blockers and unchanged-result freshness.
    Scanning current semantic inputs also catches identity/buying-chain changes
    that do not alter PowerNeed.updated_at or append a new Evidence row.
    """
    from gridlens.api.app import _commercial_triage_cards

    with SessionLocal() as session:
        cards = _commercial_triage_cards(session, 50)
        present = {card["id"] for card in cards}
        covered = present | {
            need_id for card in cards for need_id in card.get("related_need_ids", [])
        }
        targets = {
            str(need_id)
            for need_id in session.scalars(select(PowerNeed.id).where(PowerNeed.active))
            if str(need_id) not in covered
        }
        for identity in session.scalars(
            select(Pursuit.identity_key)
            .where(Pursuit.identity_key.like("commercial-need:%"))
            .order_by(Pursuit.identity_key)
        ):
            value = identity.removeprefix("commercial-need:")
            try:
                UUID(value)
            except ValueError:
                continue
            if value not in present:
                targets.add(value)
        ordered_targets = sorted(targets)
        projected = evaluate_targets(session, ordered_targets, cohort=cards, grouped=True)
        additional: dict[str, dict] = {}
        for target in ordered_targets:
            card = projected.get(target)
            if card is not None and card["id"] not in present:
                additional.setdefault(card["id"], card)
        return cards + list(additional.values())


def current_card(need_id: UUID) -> dict | None:
    with SessionLocal() as session:
        return evaluate_target(session, need_id)


def process_question_job(job_id: UUID, worker_id: str, fence: int) -> None:
    started = time.monotonic()
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        row = session.get(PursuitResearchQuestion, job.target_id)
        if row is None:
            raise LookupError("Research question target is missing")
        question_id, need_id = row.id, row.need_id
        if row.status not in ACTIVE:
            job.status, job.lease_owner, job.lease_until = "succeeded", None, None
            return
        row.attempt_count += 1
        ambiguous = bool(row.receipt.get("inflight_url"))
        context, budget = dict(row.context), dict(row.budget)
        expected_hash = row.evidence_fingerprint
        row.status = "SEARCHING"
        row.receipt = {
            "searches": 0,
            "model_calls": 0,
            "cost_usd": "0",
            **row.receipt,
            "started_at": row.receipt.get("started_at") or datetime.now(UTC).isoformat(),
            "latest_attempt_at": datetime.now(UTC).isoformat(),
            "queries_generated": context["queries"],
            "route_results": context.get("route_plan", []),
        }
        records = [
            (
                item["source_id"],
                item["external_id"],
                item["url"],
                item["family"],
                item["retrieval_method"],
            )
            for item in selected_sources(session, need_id)
            if item["enabled"] or item["targeted_only"]
        ]

    if ambiguous:
        with SessionLocal.begin() as session:
            row = session.get(PursuitResearchQuestion, question_id)
            assert row is not None
            row.receipt = {
                **row.receipt,
                "ambiguous_effects": [
                    *row.receipt.get("ambiguous_effects", []),
                    {"url": row.receipt["inflight_url"], "status": "UNKNOWN"},
                ],
            }
        _finish(
            job_id,
            worker_id,
            fence,
            question_id,
            "FAILED",
            started,
            error="ambiguous_prior_retrieval",
        )
        return
    run = QuestionRun(job_id, worker_id, fence, question_id, started, budget)
    card = current_card(need_id)
    with SessionLocal() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row is not None
        project = session.get(Project, row.project_id)
        assert project is not None
        current_hash = fingerprint([card["input_hash"], project.identity_key]) if card else None
        routes_current = routing_context(row.category, selected_sources(session, row.need_id))
        source_changed = bool(
            context.get("selected_source_fingerprint")
            and context["selected_source_fingerprint"]
            != routes_current["selected_source_fingerprint"]
        )
    if current_hash != expected_hash or source_changed:
        _finish(
            job_id,
            worker_id,
            fence,
            question_id,
            "FAILED",
            started,
            error="input_changed_before_research",
        )
        return
    assert card is not None
    # Explicit mode guarantees that Houston and every other route performs zero I/O.
    with SessionLocal.begin() as session:
        assert_fence(session, job_id, worker_id, fence)
        row = session.get(PursuitResearchQuestion, question_id)
        assert row is not None
        project = session.get(Project, row.project_id)
        need = session.get(PowerNeed, row.need_id)
        assert project is not None and need is not None
        retained_results = replay_retained_research(session, project, need)
        enrich_buying_chain(session, row.project_id, retained_only=True)
    for retained_result in retained_results:
        run.record(retained_result)
    resolved = blocker_resolved(context["category"], current_card(need_id) or card, context)
    run.route(
        "retained",
        "RESOLVED" if resolved else "CHECKED",
        reason="Checked current canonical evidence and retained buying-chain relationships.",
    )
    known_urls: set[str] = set()
    try:
        # Authoritative adapters precede known public pages; discovery is last.
        ordered_records = sorted(records, key=lambda record: record[0] not in SUPPORTED_SOURCES)
        for source_id, external_id, url, family, method in [] if resolved else ordered_records:
            if url in known_urls:
                continue
            if len(known_urls) >= budget["urls"]:
                raise BudgetExceeded("Candidate URL bound reached")
            known_urls.add(url)
            if source_id not in SUPPORTED_SOURCES:
                if family == "news" and method == "publisher-rss":
                    if len(known_urls) > budget["urls"]:
                        raise BudgetExceeded("Candidate URL bound reached")
                    _research_public_url(run, url)
                    run.route("public", "CHECKED", url=url)
                    resolved = blocker_resolved(
                        context["category"], current_card(need_id) or card, context
                    )
                    if resolved:
                        break
                else:
                    # Structured official sources must keep their registered
                    # interpretation; an unsupported feed is not a news page.
                    run.limitation(f"No bounded exact-record research adapter for {source_id}.")
                continue
            key = fingerprint([source_id, external_id])
            with SessionLocal.begin() as guard:
                # Serialize identical URL/record retrieval across different questions.
                _lock_acquisition(guard, key)
                cached = run.cached(key)
                if cached:
                    run.record({**cached, "cache_reused": True})
                else:
                    try:
                        source, record = acquire_registered_record(
                            source_id,
                            external_id,
                            deadline=run.deadline,
                            before_request=run.reserve,
                            max_bytes=budget["document_bytes"],
                        )
                        with SessionLocal.begin() as session:
                            assert_fence(session, job_id, worker_id, fence)
                            row = session.get(PursuitResearchQuestion, question_id)
                            assert row is not None
                            project = session.get(Project, row.project_id)
                            need = session.get(PowerNeed, row.need_id)
                            assert project is not None and need is not None
                            result = retain_registered_record(
                                session,
                                project,
                                need,
                                source,
                                record,
                                job_id=job_id,
                                worker_id=worker_id,
                                fence=fence,
                            )
                            if result["disposition"] == "ACCEPTED":
                                enrich_buying_chain(session, project.id, retained_only=True)
                        run.record(
                            {
                                **result,
                                "acquisition_key": key,
                                "source_version": _record_version(source_id, external_id),
                            }
                        )
                    except BudgetExceeded:
                        raise
                    except Exception as exc:
                        with SessionLocal() as session:
                            pending = session.get(PursuitResearchQuestion, question_id)
                            assert pending is not None
                            receipt = pending.receipt
                            dispatched = bool(receipt.get("inflight_url"))
                        run.record(
                            {
                                "url": url,
                                "disposition": "FAILED",
                                "effect_status": "UNKNOWN" if dispatched else "NOT_SENT",
                                **retrieval_failure(exc),
                                "acquisition_key": key,
                            }
                        )
            run.route("registered", "CHECKED", source_id=source_id, external_id=external_id)
            resolved = blocker_resolved(context["category"], current_card(need_id) or card, context)
            if resolved:
                break
        # Discovery is URL-only; snippets are never submitted for evidence admission.
        if not resolved:
            if not settings.firecrawl_api_key:
                run.route(
                    "discovery", "UNAVAILABLE", reason="Firecrawl discovery is not configured."
                )
                run.limitation(
                    "Firecrawl discovery is not configured; "
                    "broader public search was not performed."
                )
            elif settings.firecrawl_search_cost_usd is None:
                run.route("discovery", "UNAVAILABLE", reason="Search unit cost is unconfigured.")
                run.limitation(
                    "Search unit cost is unconfigured; paid discovery was not performed."
                )
            else:
                for query in context["queries"][: budget["searches"]]:
                    if len(known_urls) >= budget["urls"]:
                        raise BudgetExceeded("Candidate URL bound reached")
                    candidates = discover_urls(
                        query,
                        api_key=settings.firecrawl_api_key.get_secret_value(),
                        deadline=run.deadline,
                        before_request=partial(run.reserve, query=query),
                        limit=min(budget["urls"], 10),
                    )
                    run.complete_search(query)
                    family = next(
                        (
                            item["family"]
                            for item in context.get("query_routes", [])
                            if item["query"] == query
                        ),
                        "public-web",
                    )
                    run.route("discovery", "CHECKED", family=family, query=query)
                    for url in candidates:
                        if url in known_urls:
                            continue
                        if len(known_urls) >= budget["urls"]:
                            break
                        known_urls.add(url)
                        _research_public_url(run, url)
                        resolved = blocker_resolved(
                            context["category"], current_card(need_id) or card, context
                        )
                        if resolved:
                            break
                    if resolved:
                        break
        status = "RESOLVED" if resolved else run.unresolved_status()
    except AcquisitionBusy:
        run.limitation("Another question is retrieving this source; no duplicate request was sent.")
        status = run.unresolved_status()
    except BudgetExceeded:
        status = "BUDGET_EXCEEDED"
    except Exception as exc:
        failure = retrieval_failure(exc)
        run.limitation(f"Discovery failed: {failure['failure_code']}.")
        with SessionLocal() as session:
            pending = session.get(PursuitResearchQuestion, question_id)
            assert pending is not None
            receipt = pending.receipt
            dispatched = bool(receipt.get("inflight_url"))
        run.record(
            {
                "url": "https://api.firecrawl.dev/v2/search",
                "disposition": "FAILED",
                "effect_status": "UNKNOWN" if dispatched else "NOT_SENT",
                "acquisition_method": "firecrawl_discovery",
                **failure,
            }
        )
        status = "FAILED"
    _finish(job_id, worker_id, fence, question_id, status, started)


def _research_public_url(run: QuestionRun, url: str) -> None:
    """One retained/discovered public page through the same bounded admission path."""
    key = fingerprint(url)
    with SessionLocal.begin() as guard:
        _lock_acquisition(guard, key)
        cached = run.cached(key)
        if cached:
            run.record({**cached, "cache_reused": True})
            return
        direct_failure = None
        try:
            run.reserve(url)
            acquisition_method = "direct_http"
            try:
                document = retrieve(
                    url, deadline=run.deadline, max_bytes=run.budget["document_bytes"]
                )
            except PublicExtractionUnavailable as exc:
                direct_failure = retrieval_failure(exc)
                if not settings.firecrawl_api_key or settings.firecrawl_scrape_cost_usd is None:
                    raise ExtractionUnavailable(
                        "Firecrawl extraction or unit cost is not configured"
                    ) from None
                document = extract_public_document(
                    url,
                    api_key=settings.firecrawl_api_key.get_secret_value(),
                    deadline=run.deadline,
                    max_bytes=run.budget["document_bytes"],
                    before_request=run.reserve_extraction,
                )
                acquisition_method = "firecrawl_html_extraction"
            with SessionLocal.begin() as session:
                row = run.row(session)
                row.status = "REVIEWING_EVIDENCE"
                project = session.get(Project, row.project_id)
                need = session.get(PowerNeed, row.need_id)
                assert project is not None and need is not None
                result = retain_research_document(session, project, need, document)
                if result["disposition"] == "ACCEPTED":
                    enrich_buying_chain(session, project.id, retained_only=True)
            run.record(
                {
                    **result,
                    "acquisition_key": key,
                    "document_hash": fingerprint(document.text),
                    "acquisition_method": acquisition_method,
                    "direct_failure": direct_failure,
                }
            )
        except BudgetExceeded:
            raise
        except Exception as exc:
            with SessionLocal() as session:
                pending = session.get(PursuitResearchQuestion, run.question_id)
                assert pending is not None
                receipt = pending.receipt
                dispatched = bool(receipt.get("inflight_url"))
            run.record(
                {
                    "url": url,
                    "disposition": "FAILED",
                    "effect_status": "UNKNOWN" if dispatched else "NOT_SENT",
                    **retrieval_failure(exc),
                    "direct_failure": direct_failure,
                    "acquisition_key": key,
                }
            )


class AcquisitionBusy(Exception):
    """Another bounded question owns this source; never wait beyond our budget."""


def _lock_acquisition(session, key: str) -> None:
    if not session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 29))"), {"key": key}
    ):
        raise AcquisitionBusy()


class BudgetExceeded(Exception):
    """Persisted attempt cap or deadline prevents another external call."""


def _record_version(source_id: str, external_id: str) -> str | None:
    with SessionLocal() as session:
        return session.scalar(
            select(Observation.content_hash).where(
                Observation.source_id == source_id, Observation.external_id == external_id
            )
        )


class QuestionRun:
    def __init__(self, job_id, worker_id, fence, question_id, started, budget):
        self.job_id, self.worker_id, self.fence = job_id, worker_id, fence
        self.question_id, self.budget = question_id, budget
        self.deadline = started + budget["timeout_seconds"]

    def row(self, session):
        assert_fence(session, self.job_id, self.worker_id, self.fence)
        row = session.get(PursuitResearchQuestion, self.question_id)
        assert row is not None
        return row

    def reserve(self, url: str, *, query: str | None = None) -> None:
        with SessionLocal.begin() as session:
            row = self.row(session)
            receipt = dict(row.receipt)
            count_key = "searches" if query else "retrieval_attempts"
            limit = self.budget["searches" if query else "documents"]
            cost = Decimal(receipt.get("reserved_cost_usd", "0"))
            next_cost = cost + (settings.firecrawl_search_cost_usd or Decimal(0)) if query else cost
            if (
                time.monotonic() >= self.deadline
                or receipt.get(count_key, 0) >= limit
                or (query and receipt.get("retrieval_attempts", 0) >= self.budget["documents"])
                or next_cost > Decimal(self.budget["max_cost_usd"])
            ):
                raise BudgetExceeded()
            if query and query in receipt.get("queries_attempted", []):
                raise BudgetExceeded("Identical query already attempted")
            receipt[count_key] = receipt.get(count_key, 0) + 1
            if query:
                # This callback runs at paid-provider dispatch. An interrupted
                # request remains ambiguous and blocks blind retries.
                receipt["inflight_url"] = url
            else:
                # A free public/source GET is idempotent and is not a paid side effect.
                receipt["inflight_acquisition_url"] = url
            receipt["reserved_cost_usd"] = str(next_cost)
            if query:
                # Reservation is an upper bound, not a provider billing receipt.
                receipt["cost_usd"] = None
            if query:
                receipt["queries_attempted"] = [*receipt.get("queries_attempted", []), query]
            row.receipt = receipt

    def reserve_extraction(self, url: str) -> None:
        """A second acquisition is separately bounded and charged before I/O."""
        unit_cost = settings.firecrawl_scrape_cost_usd
        if unit_cost is None:
            raise ExtractionUnavailable("Firecrawl extraction unit cost is not configured")
        with SessionLocal.begin() as session:
            row = self.row(session)
            receipt = dict(row.receipt)
            next_cost = Decimal(receipt.get("reserved_cost_usd", "0")) + unit_cost
            if (
                time.monotonic() >= self.deadline
                or receipt.get("retrieval_attempts", 0) >= self.budget["documents"]
                or next_cost > Decimal(self.budget["max_cost_usd"])
            ):
                raise BudgetExceeded("Extraction exceeds persisted time/document/cost budget")
            receipt["retrieval_attempts"] = receipt.get("retrieval_attempts", 0) + 1
            receipt["firecrawl_extractions"] = receipt.get("firecrawl_extractions", 0) + 1
            receipt["inflight_url"] = url
            receipt["reserved_cost_usd"] = str(next_cost)
            receipt["cost_usd"] = None  # Reservation is not a provider billing receipt.
            row.receipt = receipt

    def complete_search(self, query: str) -> None:
        with SessionLocal.begin() as session:
            row = self.row(session)
            row.receipt = {
                **row.receipt,
                "inflight_url": None,
                "queries_searched": [*row.receipt.get("queries_searched", []), query],
            }

    def route(
        self,
        kind: str,
        status: str,
        *,
        reason: str | None = None,
        query: str | None = None,
        **identity: str,
    ) -> None:
        with SessionLocal.begin() as session:
            row = self.row(session)
            routes = []
            for route in row.receipt.get("route_results", []):
                if route["kind"] == kind and all(
                    route.get(key) == value for key, value in identity.items()
                ):
                    route = {**route, "status": status, "reason": reason}
                    if query:
                        route["query"] = query
                routes.append(route)
            row.receipt = {**row.receipt, "route_results": routes}

    def limitation(self, message: str) -> None:
        with SessionLocal.begin() as session:
            row = self.row(session)
            row.receipt = {
                **row.receipt,
                "acquisition_limitations": list(
                    dict.fromkeys([*row.receipt.get("acquisition_limitations", []), message])
                ),
            }

    def record(self, result: dict) -> None:
        with SessionLocal.begin() as session:
            row = self.row(session)
            checks = list(row.receipt.get("source_checks", []))
            result = {
                **result,
                "checked_at": result.get("checked_at")
                if result.get("cache_reused")
                else datetime.now(UTC).isoformat(),
            }
            checks.append(result)
            accepted = list(row.receipt.get("resulting_evidence_ids", []))
            if result["disposition"] == "ACCEPTED" and result.get("evidence_id"):
                accepted.append(result["evidence_id"])
            row.receipt = {
                **row.receipt,
                # An exception after reservation may have followed a sent
                # request. Preserve it as UNKNOWN; only successful completion
                # or a confirmed pre-send failure can clear the reservation.
                "inflight_url": (
                    row.receipt.get("inflight_url")
                    if result.get("disposition") == "FAILED"
                    and result.get("effect_status") == "UNKNOWN"
                    else None
                ),
                "inflight_acquisition_url": None,
                "ambiguous_effects": (
                    [
                        *row.receipt.get("ambiguous_effects", []),
                        {
                            "url": row.receipt.get("inflight_url"),
                            "status": "UNKNOWN",
                            "acquisition_key": result.get("acquisition_key"),
                        },
                    ]
                    if result.get("disposition") == "FAILED"
                    and result.get("effect_status") == "UNKNOWN"
                    and row.receipt.get("inflight_url")
                    else row.receipt.get("ambiguous_effects", [])
                ),
                "source_checks": checks,
                "resulting_evidence_ids": sorted(set(accepted)),
                "duplicate_work_avoided": row.receipt.get("duplicate_work_avoided", 0)
                + int(bool(result.get("cache_reused") or result.get("duplicate"))),
            }
            row.status = "SEARCHING"

    def cached(self, key: str) -> dict | None:
        with SessionLocal() as session:
            row = session.get(PursuitResearchQuestion, self.question_id)
            assert row is not None
            if row.context.get("force"):
                return None
            cutoff = datetime.now(UTC) - timedelta(hours=min(row.context["freshness_hours"], 24))
            others = session.scalars(
                select(PursuitResearchQuestion)
                .where(
                    PursuitResearchQuestion.project_id == row.project_id,
                    PursuitResearchQuestion.created_at >= cutoff,
                )
                .order_by(PursuitResearchQuestion.created_at.desc())
            )
            for prior in others:
                for result in reversed(prior.receipt.get("source_checks", [])):
                    if result.get("acquisition_key") != key or result["disposition"] == "FAILED":
                        continue
                    if datetime.fromisoformat(result["checked_at"]) < cutoff:
                        continue
                    if prior.context.get("selected_source_fingerprint") != row.context.get(
                        "selected_source_fingerprint"
                    ) or prior.context.get("policy_version") != row.context.get("policy_version"):
                        continue
                    # Only immutable admitted evidence can be reused across questions.
                    evidence_id = result.get("evidence_id")
                    evidence = session.get(Evidence, UUID(evidence_id)) if evidence_id else None
                    observation = (
                        session.get(Observation, evidence.observation_id) if evidence else None
                    )
                    if (
                        evidence
                        and observation
                        and result.get("source_version")
                        and observation.content_hash != result["source_version"]
                    ):
                        continue
                    if evidence and (
                        result.get("source_version")
                        or (observation and observation.content_hash == evidence.content_hash)
                    ):
                        if result["disposition"] != "ACCEPTED" or _current_support(
                            session, row, evidence, observation, result
                        ):
                            return result
                    if result.get("document_hash") and result["disposition"] == "REJECTED":
                        identity_fields = ("site_address", "stable_identifiers", "name")
                        if all(
                            prior.context.get(field) == row.context.get(field)
                            for field in identity_fields
                        ):
                            return result
            return None

    def unresolved_status(self) -> str:
        with SessionLocal() as session:
            row = session.get(PursuitResearchQuestion, self.question_id)
            assert row is not None
            checks = row.receipt.get("source_checks", [])
            category, context, need_id = row.category, row.context, row.need_id
        after = current_card(need_id)
        if after and _question_partial_progress(
            category, context.get("before", {}), after, context
        ):
            return "PARTIALLY_RESOLVED"
        external = [c for c in checks if c.get("acquisition") != "retained"]
        if external and all(c["disposition"] == "FAILED" for c in external):
            return "FAILED"
        return "UNRESOLVED"


def _question_partial_progress(category: str, before: dict, after: dict, context: dict) -> bool:
    """Measure answered components of this question, never unrelated admission volume."""
    if category == "supply":
        fields = {"permanent_service", "supply_adequacy"}
    elif category == "conflict":
        fields = set(context.get("conflict_fields", []))
    else:
        return False  # Single-fact questions are resolved or still unanswered.
    if not fields:
        return False

    def answered(card: dict) -> set[str]:
        state = card.get("research_state", {})
        return {
            field
            for field in fields
            if state.get(field, {}).get("status") == "SUPPORTED" and state[field].get("claims")
        }

    prior, current = answered(before), answered(after)
    return prior < current < fields


def _current_support(session, question, evidence, observation, result) -> bool:
    """Content equality alone is not current accepted canonical support."""
    from gridlens.domain.signal_admission import admitted_from_source
    from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION

    if observation is None:
        return False
    interpretation = session.scalar(
        select(Interpretation).where(Interpretation.observation_id == observation.id)
    )
    project = session.get(Project, question.project_id)
    need = session.get(PowerNeed, question.need_id)
    source = session.get(Source, observation.source_id)
    assessment = interpretation.assessment if interpretation else None
    if observation.source_id.startswith("research-public-") and (assessment or {}).get(
        "acquisition_capture_version"
    ) != CAPTURE_VERSION:
        return False
    if not (
        interpretation
        and project
        and need
        and source
        and assessment
        and interpretation.content_hash == observation.content_hash
        and assessment.get("evidence_hash") == evidence.content_hash
        and assessment.get("project_identity_key") == project.identity_key
    ):
        return False
    if result.get("canonical_support_withdrawn"):
        return interpretation.status == "rejected" and not need.active
    linked = session.scalar(
        select(NeedObservation.id).where(
            NeedObservation.observation_id == observation.id, NeedObservation.need_id == need.id
        )
    )
    if linked and assessment.get("admission_status") == "project_research_supplement":
        from gridlens.intelligence.project_state import current_research_state

        fields = current_research_state(session, project.id, need.id).get(str(need.id), {})
        return any(
            claim.get("evidence_id") == str(evidence.id)
            for field in fields.values()
            for claim in field.get("claims", [])
        )
    if linked and assessment.get("admission_status") == "relationship_supplement":
        from gridlens.intelligence.buying_chain import _retained_evidence_current_for_project

        return need.active and _retained_evidence_current_for_project(session, project, evidence)
    return bool(
        interpretation.status == "accepted"
        and linked
        and (assessment.get("power_activity") or assessment.get("activity_key"))
        == need.activity_key
        and (
            admitted_from_source(source, assessment, evidence).admitted
            or assessment.get("admission_status") == "supplemental"
        )
    )


def _finish(
    job_id: UUID,
    worker_id: str,
    fence: int,
    question_id: UUID,
    status: str,
    started: float,
    *,
    error: str | None = None,
) -> None:
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        row = session.get(PursuitResearchQuestion, question_id)
        assert row is not None
        card = evaluate_target(session, row.need_id)
        if card:
            save_evaluations(session, [card])
        now = datetime.now(UTC)
        row.status, row.completed_at = status, now
        checked_route = any(
            route.get("status") == "CHECKED" and route.get("kind") != "retained"
            for route in row.receipt.get("route_results", [])
        ) or any(
            check.get("acquisition") != "retained"
            and check.get("disposition") in {"ACCEPTED", "REJECTED", "UNRESOLVED"}
            for check in row.receipt.get("source_checks", [])
        ) or bool(row.receipt.get("queries_searched"))
        failed_external_check = any(
            check.get("acquisition") != "retained" and check.get("disposition") == "FAILED"
            for check in row.receipt.get("source_checks", [])
        )
        retryable = status in {"FAILED", "BUDGET_EXCEEDED"} or (
            status in {"UNRESOLVED", "PARTIALLY_RESOLVED"}
            and (not checked_route or failed_external_check)
        )
        retryable = retryable and not (
            row.receipt.get("inflight_url") or row.receipt.get("ambiguous_effects")
        )
        retry_after = _retry_deadline(row, now) if retryable else None
        row.retry_after = retry_after or now + timedelta(hours=row.context["freshness_hours"])
        retry_class = (
            "UNKNOWN_EFFECT"
            if row.receipt.get("inflight_url") or row.receipt.get("ambiguous_effects")
            else "BOUNDED_TRANSIENT"
            if retry_after is not None
            else "RETRIES_EXHAUSTED"
            if retryable
            else "FRESH_CHECK"
        )
        project = session.get(Project, row.project_id)
        assert project is not None
        row.receipt = {
            **row.receipt,
            "error": error,
            "route_results": [
                {
                    **route,
                    "status": "SKIPPED" if status == "RESOLVED" else "NOT_REACHED",
                    "reason": "Stopped after a supported answer."
                    if status == "RESOLVED"
                    else "Attempt ended before this route; inspect budget/error/source receipts.",
                }
                if route["status"] == "PLANNED"
                else route
                for route in row.receipt.get("route_results", [])
            ],
            "result_disposition": status,
            "retry_class": retry_class,
            "runtime_seconds": round(time.monotonic() - started, 3),
            "reevaluation_status": "COMPLETED" if card else "NO_CURRENT_SUPPORT",
            "before": row.context["before"]["disposition"],
            "after": card["disposition"] if card else None,
            "after_input_hash": card["input_hash"] if card else None,
            "post_evidence_fingerprint": fingerprint([card["input_hash"], project.identity_key])
            if card
            else None,
            "reason": card["reason"] if card else "No currently supported target card",
            "remaining_blockers": card.get("blockers", []) if card else [],
            "next_action": card["next_action"] if card else None,
            "tier": card["tier"] if card else None,
        }
        job.status = "failed" if status == "FAILED" else "succeeded"
        job.error, job.lease_owner, job.lease_until = error, None, None
        parent_id = row.id if row.parent_id is None and status == "RESOLVED" else None
    if parent_id and card and card["disposition"] == "RESEARCH":
        from gridlens.intelligence.pursuit_questions import schedule_questions

        with SessionLocal.begin() as session:
            schedule_questions(session, [card], parent_id=parent_id)


def _retry_deadline(row: PursuitResearchQuestion, now: datetime) -> datetime | None:
    """Return a finite retry time; an UNKNOWN paid effect blocks retries."""
    if row.receipt.get("inflight_url") or row.receipt.get("ambiguous_effects"):
        return None
    attempt = int(row.context.get("retry_index", 0)) + 1
    if attempt > len(RETRY_BACKOFF_HOURS):
        return None
    return now + timedelta(hours=RETRY_BACKOFF_HOURS[attempt - 1])
