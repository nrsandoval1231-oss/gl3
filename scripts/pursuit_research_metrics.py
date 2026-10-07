"""Read-only receipt metrics. Evaluation versions, not question snapshots, count changes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        type=datetime.fromisoformat,
        help="Timezone-aware ISO timestamp; transitions use evaluation time",
    )
    args = parser.parse_args()
    if args.since is not None and args.since.tzinfo is None:
        parser.error("--since must include a timezone")
    from sqlalchemy import select

    from gridlens.intelligence.autonomous_research import current_cards
    from gridlens.intelligence.research_metrics import metrics_report
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import Pursuit, PursuitResearchQuestion

    cards = current_cards()
    with SessionLocal() as session:
        report = metrics_report(
            cards,
            list(session.scalars(select(PursuitResearchQuestion))),
            list(session.scalars(select(Pursuit))),
            args.since,
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
