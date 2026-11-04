"""Print the first-signal sample as JSON lines (internal, read-only; no network, no writes)."""

import argparse
import json
from datetime import datetime

from gridlens.intelligence.first_signal import first_signal_sample
from gridlens.persistence.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--since", help="ISO timestamp (first_seen_at lower bound)")
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since) if args.since else None
    with SessionLocal() as session:
        for row in first_signal_sample(session, source_ids=args.sources, since=since):
            print(json.dumps(row, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
