"""Report deterministic decisions for already-retained RSS items; no retrieval occurs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.domain.news_interpretation import EVALUATOR_VERSION, assess_news  # noqa: E402


def interpret_rows(
    rows: list[dict[str, Any]], limit: int | None = None
) -> dict[str, Any]:
    rss_rows = [row for row in rows if str(row.get("source_id", "")).endswith("-news")]
    rss_rows.sort(
        key=lambda row: (row["source_id"], row["external_id"], row["content_hash"])
    )
    if limit is not None:
        rss_rows = rss_rows[:limit]
    decisions = []
    for row in rss_rows:
        assessment = assess_news(row["title"], row.get("excerpt"))
        decisions.append(
            {
                "source_id": row["source_id"],
                "external_id": row["external_id"],
                "content_hash": row["content_hash"],
                "published_at": row["published_at"],
                "title": row["title"],
                "citation_url": row["citation_url"],
                "assessment": assessment.as_dict(),
            }
        )
    counts = Counter(
        f"{decision['assessment']['decision']}:{decision['assessment']['tier'] or 'none'}"
        for decision in decisions
    )
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "mode": "dry-run",
        "source_count": len(rss_rows),
        "counts": dict(sorted(counts.items())),
        "decisions": decisions,
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
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist decisions transactionally to DATABASE_URL",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.apply:
        from sqlalchemy import select

        from gridlens.ingestion.service import assess_retained_news
        from gridlens.persistence.database import SessionLocal
        from gridlens.persistence.models import (
            Evidence,
            Interpretation,
            Observation,
            Source,
        )

        decisions: list[dict[str, Any]] = []
        failed = 0
        with SessionLocal.begin() as session:
            observations = session.scalars(
                select(Observation)
                .join(Source, Source.id == Observation.source_id)
                .where(Source.retrieval_method == "publisher-rss")
                .order_by(Observation.source_id, Observation.external_id)
            ).all()
            if args.limit is not None:
                observations = observations[: args.limit]
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
                assessment = (
                    interpretation.assessment if interpretation else None
                ) or {}
                status = interpretation.status if interpretation else "missing"
                if status in {"failed", "pending"}:
                    failed += 1
                decisions.append(
                    {
                        "source_id": observation.source_id,
                        "external_id": observation.external_id,
                        "content_hash": observation.content_hash,
                        "published_at": observation.published_at.isoformat(),
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
        from collections import Counter

        counts = Counter(
            f"{row['assessment'].get('decision')}:{row['assessment'].get('tier') or 'none'}"
            for row in decisions
        )
        report = {
            "evaluator_version": EVALUATOR_VERSION,
            "mode": "apply",
            "source_count": len(decisions),
            "counts": dict(sorted(counts.items())),
            "decisions": decisions,
            "database": "DATABASE_URL current retained observations",
            "failed_or_pending": failed,
        }
    else:
        rows = json.loads(args.input.read_text(encoding="utf-8"))
        report = interpret_rows(rows, args.limit)
        report["input"] = str(args.input)
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
