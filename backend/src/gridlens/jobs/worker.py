import os
import socket
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.jobs.queue import assert_fence, lease_one
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import Job, PowerNeedBrief, Source
from gridlens.settings import settings

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


def sync_registry() -> list[dict]:
    definitions = load_registry()
    with SessionLocal.begin() as session:
        for item in definitions:
            row = session.get(Source, item["id"])
            values = {
                key: item[key]
                for key in (
                    "publisher",
                    "endpoint",
                    "family",
                    "geography",
                    "industries",
                    "retrieval_method",
                    "cadence_hours",
                    "enabled",
                )
            }
            if row is None:
                row = Source(id=item["id"], **values, health={"status": "Overdue"})
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
    return definitions


def refresh_due() -> int:
    definitions = sync_registry()
    created = 0
    with SessionLocal.begin() as session:
        now = datetime.now(UTC)
        from gridlens.jobs.queue import enqueue

        for item in definitions:
            source = session.get(Source, item["id"])
            assert source is not None
            last = source.health.get("last_attempt")
            due = not last or datetime.fromisoformat(last) <= now - timedelta(
                hours=item["cadence_hours"]
            )
            if item["enabled"] and due:
                enqueue(session, item["id"])
                created += 1
    return created


def run_one(definitions: dict[str, dict], *, job_ids: list[UUID] | None = None) -> bool:
    with SessionLocal.begin() as session:
        leased = lease_one(session, WORKER_ID, lease_seconds=600, job_ids=job_ids)
        if leased is None:
            return False
        job, fence = leased
        job_id, source_id, kind = job.id, job.source_id, job.kind
        source = session.get(Source, source_id)
        if source and kind == "ingestion":
            source.health = {
                **source.health,
                "status": "Running",
                "last_attempt": datetime.now(UTC).isoformat(),
            }
    definition = definitions[source_id]
    attempted = datetime.now(UTC).isoformat()
    try:
        if kind == "pursuit_research":
            from gridlens.intelligence.pursuits import process_research_job

            process_research_job(job_id, WORKER_ID, fence)
            return True
        if kind == "power_need_brief":
            from gridlens.intelligence.briefs import process_brief_job

            try:
                process_brief_job(job_id, WORKER_ID, fence)
            except Exception as exc:
                # Brief jobs may have reached a billable provider request. Any
                # unexpected failure is terminal; retry requires an owner action.
                with SessionLocal.begin() as session:
                    failed = session.get(Job, job_id)
                    valid = bool(
                        failed
                        and failed.status == "running"
                        and failed.lease_owner == WORKER_ID
                        and failed.fence == fence
                    )
                    if valid and failed:
                        brief = (
                            session.get(PowerNeedBrief, failed.target_id)
                            if failed.target_id
                            else None
                        )
                        if brief and brief.status == "pending":
                            brief.status = "failed"
                            brief.error = (
                                "ambiguous_prior_request"
                                if failed.checkpoint and '"reserved": true' in failed.checkpoint
                                else "worker_failed"
                            )
                        failed.status, failed.error = "failed", type(exc).__name__
                        failed.lease_owner, failed.lease_until = None, None
            return True
        with SessionLocal() as session:
            counts = process_job(session, job_id, WORKER_ID, fence, definition)
            finished_job = session.get(Job, job_id)
            source = session.get(Source, source_id)
            assert finished_job and source
            assert_fence(session, job_id, WORKER_ID, fence)
            (
                finished_job.status,
                finished_job.lease_until,
                finished_job.lease_owner,
                finished_job.error,
            ) = "succeeded", None, None, None
            source.health = {
                **source.health,
                "status": "Updated" if counts["new"] or counts["changed"] else "Checked—No Change",
                "last_attempt": attempted,
                "last_success": attempted,
                "new_records": counts["new"],
                "changed_records": counts["changed"],
                "unchanged_records": counts["unchanged"],
                "parse_failures": 0,
                "error": None,
                "latest_publication_date": counts["latest_publication_date"],
                "collection_scope": definition.get("collection_scope"),
                "coverage_limitation": definition.get("coverage_limitation"),
                **{
                    key: counts[key]
                    for key in (
                        "retrieved_records",
                        "parsed_records",
                        "snapshot_item_count",
                        "snapshot_oldest_publication_date",
                        "snapshot_newest_publication_date",
                        "latest_permit_issue_date",
                        "latest_public_comment_deadline",
                        "earliest_public_comment_deadline",
                        "records_scanned",
                        "permit_accepted",
                        "permit_rejected",
                        "documents_extracted",
                        "unextracted_public_notice_references",
                        "generator_facts",
                        "generator_excerpts_omitted",
                        "missing_application_documents",
                    )
                    if key in counts
                },
                "pdf_candidates": counts.get("pdf_candidates", 0),
                "pdf_eligible": counts.get("pdf_eligible", 0),
                "pdf_enriched": counts.get("pdf_enriched", 0),
                "pdf_skipped_not_signal": counts.get("pdf_skipped_not_signal", 0),
                "pdf_skipped_limit": counts.get("pdf_skipped_limit", 0),
            }
            if source_id in {
                "austin-building-permits",
                "texas-rrc-drilling-permits",
                "houston-weekly-permits",
                "dallas-monthly-permits",
                "el-paso-new-commercial-permits",
            }:
                from gridlens.jobs.queue import enqueue

                research_anchor = session.get(Source, "austin-building-permits")
                if research_anchor and research_anchor.enabled:
                    enqueue(session, research_anchor.id, kind="pursuit_research")
            session.commit()
    except Exception as exc:
        with SessionLocal.begin() as session:
            failed_job = session.get(Job, job_id)
            source = session.get(Source, source_id)
            valid_owner = bool(
                failed_job
                and failed_job.fence == fence
                and failed_job.status == "running"
                and failed_job.lease_owner == WORKER_ID
                and failed_job.lease_until
                and failed_job.lease_until > datetime.now(UTC)
            )
            if failed_job and valid_owner:
                failed_job.status = "queued" if failed_job.attempts < 5 else "failed"
                failed_job.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(3600, 30 * (2**failed_job.attempts))
                )
                failed_job.lease_until, failed_job.lease_owner = None, None
                from gridlens.ingestion.adapters.federal_register import SourceParseError

                failed_job.error = (
                    str(exc)[:250] if isinstance(exc, SourceParseError) else type(exc).__name__
                )
            if source and valid_owner and kind == "ingestion":
                from gridlens.ingestion.adapters.federal_register import SourceParseError

                is_parse_error = isinstance(exc, SourceParseError)
                source.health = {
                    **source.health,
                    "status": "Failed",
                    "last_attempt": attempted,
                    "parse_failures": int(source.health.get("parse_failures", 0))
                    + int(is_parse_error),
                    "error": str(exc)[:250] if is_parse_error else type(exc).__name__,
                }
    return True


def main() -> None:
    if settings.worker_auto_refresh:
        refresh_due()
    definitions = {row["id"]: row for row in load_registry()}
    next_planning = time.monotonic() + 3600
    while True:
        if settings.worker_auto_refresh and time.monotonic() >= next_planning:
            refresh_due()
            next_planning = time.monotonic() + 3600
        if not run_one(definitions):
            time.sleep(2)


if __name__ == "__main__":
    main()
