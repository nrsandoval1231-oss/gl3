"""Reassess already-retained RSS items without retrieval or model calls.

Default mode reads a local JSON export and writes a dry-run report. Apply requires
an explicit expected database name. Application apply additionally requires a
separate owner authorization for that specific run; selecting a target is not
itself authorization. No application run is automatic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.domain.news_interpretation import EVALUATOR_VERSION, assess_news  # noqa: E402
from gridlens.domain.signal_admission import POLICY_VERSION as ADMISSION_POLICY_VERSION  # noqa: E402

MAX_ROWS = 500


def interpret_rows(
    rows: list[dict[str, Any]] | dict[str, Any], limit: int = MAX_ROWS
) -> dict[str, Any]:
    if not 1 <= limit <= MAX_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_ROWS}")
    source_rows: Any = rows
    if isinstance(rows, dict):
        source_rows = rows.get("cases", rows.get("observations", []))
    if not isinstance(source_rows, list) or any(
        not isinstance(row, dict) for row in source_rows
    ):
        raise ValueError("Retained corpus must contain a list of record objects")
    rss_rows = [
        row for row in source_rows if str(row.get("source_id", "")).endswith("-news")
    ]
    rss_rows.sort(
        key=lambda row: (
            row["source_id"],
            row.get("external_id")
            or row.get("case_id")
            or row.get("observation_id", ""),
            row.get("content_hash", ""),
        )
    )
    rss_rows = rss_rows[:limit]
    decisions = []
    for row in rss_rows:
        excerpt = row.get("excerpt", row.get("abstract"))
        assessment = assess_news(row["title"], excerpt)
        external_id = (
            row.get("external_id") or row.get("case_id") or row.get("observation_id")
        )
        decisions.append(
            {
                "source_id": row["source_id"],
                "external_id": external_id,
                "content_hash": row.get("content_hash"),
                "published_at": row["published_at"],
                "title": row["title"],
                "citation_url": row.get("citation_url", row.get("url")),
                "assessment": assessment.as_dict(),
            }
        )
    counts = Counter(
        f"{decision['assessment']['decision']}:{decision['assessment']['tier'] or 'none'}"
        for decision in decisions
    )
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
        "mode": "dry-run",
        "source_count": len(rss_rows),
        "limit": limit,
        "corpus_kind": "retained-records",
        "counts": dict(sorted(counts.items())),
        "decisions": decisions,
    }


def _database_session_factory(target_name: str, expected_database_name: str):
    """Validate the selected database identity before creating an engine."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from gridlens.settings import settings

    if target_name not in {"test", "application"}:
        raise ValueError("--database-target must be test or application")
    database_url = (
        settings.test_database_url if target_name == "test" else settings.database_url
    )
    if not database_url:
        raise ValueError(f"Reassessment target {target_name} is not configured")
    target = make_url(database_url)
    application = make_url(settings.database_url)
    if not target.database:
        raise ValueError("Reassessment target has no database name")
    if target_name == "test" and not target.database.endswith("_test"):
        raise ValueError("Test reassessment target must end in _test")
    if target.database != expected_database_name:
        raise ValueError("Target database name does not match --expected-database-name")
    if target_name == "test" and (target.host, target.port, target.database) == (
        application.host,
        application.port,
        application.database,
    ):
        raise ValueError(
            "Reassessment refuses to use the application database as the test target"
        )
    engine = create_engine(database_url)
    return engine, target.database, sessionmaker(engine, expire_on_commit=False)


def apply_retained_news(
    session_factory,
    limit: int,
    *,
    after_observation_id=None,
    include_accepted: bool = False,
) -> dict[str, Any]:
    from sqlalchemy import select
    from uuid import UUID

    from gridlens.ingestion.service import assess_retained_news
    from gridlens.persistence.models import (
        Evidence,
        Interpretation,
        Observation,
        Source,
    )

    decisions: list[dict[str, Any]] = []
    failed = 0
    with session_factory.begin() as session:
        query = (
            select(Observation)
            .join(Source, Source.id == Observation.source_id)
            .join(Interpretation, Interpretation.observation_id == Observation.id)
            .where(Source.retrieval_method == "publisher-rss")
            .where(
                Interpretation.status.in_(["accepted", "rejected", "failed", "pending"])
                if include_accepted
                else Interpretation.status == "rejected"
            )
            .order_by(Observation.id)
            .limit(limit)
        )
        if after_observation_id is not None:
            query = query.where(Observation.id > UUID(str(after_observation_id)))
        observations = session.scalars(query).all()
        for observation in observations:
            evidence_versions = session.scalars(
                select(Evidence)
                .where(Evidence.observation_id == observation.id)
                .order_by(Evidence.observed_at.desc(), Evidence.content_hash)
            ).all()
            current = next(
                (
                    item
                    for item in evidence_versions
                    if item.title == observation.title
                    and (item.abstract or "").split()
                    == (observation.abstract or "").split()
                    and item.published_at == observation.published_at
                    and item.url == observation.url
                ),
                None,
            )
            if current is None:
                raise RuntimeError(
                    f"No retained evidence matches current observation {observation.id}"
                )
            assess_retained_news(session, observation, current)
            session.flush()
            interpretation = session.scalar(
                select(Interpretation).where(
                    Interpretation.observation_id == observation.id
                )
            )
            assessment = (interpretation.assessment if interpretation else None) or {}
            status = interpretation.status if interpretation else "missing"
            if status in {"failed", "pending"}:
                failed += 1
            decisions.append(
                {
                    "source_id": observation.source_id,
                    "external_id": observation.external_id,
                    "content_hash": observation.content_hash,
                    "published_at": (
                        observation.published_at.isoformat()
                        if observation.published_at
                        else None
                    ),
                    "title": observation.title,
                    "citation_url": observation.url,
                    "status": status,
                    "error": interpretation.error
                    if interpretation
                    else "missing_interpretation",
                    "assessment": {
                        key: value
                        for key, value in assessment.items()
                        if key != "previous_decisions"
                    },
                }
            )
    counts = Counter(
        f"{row['assessment'].get('decision')}:{row['assessment'].get('tier') or 'none'}"
        for row in decisions
    )
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
        "mode": "apply-including-accepted"
        if include_accepted
        else "apply-rejected-only",
        "source_count": len(decisions),
        "next_cursor": str(observations[-1].id) if observations else None,
        "counts": dict(sorted(counts.items())),
        "decisions": decisions,
        "failed_or_pending": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(".artifacts/project-candidates-baseline.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".artifacts/GL3-007/dry-run.json")
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_ROWS,
        help=f"Maximum records to reassess (1-{MAX_ROWS})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist to selected database; application requires separate owner authorization",
    )
    parser.add_argument(
        "--database-target", choices=("test", "application"), default="test"
    )
    parser.add_argument("--expected-database-name")
    parser.add_argument("--after-observation-id", type=UUID)
    parser.add_argument(
        "--include-accepted",
        action="store_true",
        help="also re-evaluate accepted RSS records; apply defaults to rejected records only",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_ROWS:
        parser.error(f"--limit must be between 1 and {MAX_ROWS}")
    if args.include_accepted and not args.apply:
        parser.error("--include-accepted requires --apply")
    if args.apply and not args.expected_database_name:
        parser.error("--apply requires --expected-database-name")
    if args.apply:
        try:
            engine, database_name, apply_sessions = _database_session_factory(
                args.database_target, args.expected_database_name
            )
        except ValueError as exc:
            parser.error(str(exc))
        try:
            report = apply_retained_news(
                apply_sessions,
                args.limit,
                after_observation_id=args.after_observation_id,
                include_accepted=args.include_accepted,
            )
            report["database"] = database_name
            report["database_target"] = args.database_target
        finally:
            if engine is not None:
                engine.dispose()
    else:
        input_bytes = args.input.read_bytes()
        rows = json.loads(input_bytes)
        report = interpret_rows(rows, args.limit)
        report["input"] = str(args.input)
        report["corpus_sha256"] = hashlib.sha256(input_bytes).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "mode": report["mode"],
                "source_count": report["source_count"],
                "counts": report["counts"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    if report.get("failed_or_pending", 0):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
