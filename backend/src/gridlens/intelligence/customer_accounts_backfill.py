"""Apply bounded retained-evidence RRC identity backfill and rebuild saved browse."""

from __future__ import annotations

import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.customer_accounts import backfill_rrc_operator_memberships
from gridlens.intelligence.saved_browse import rebuild
from gridlens.settings import settings


def main() -> int:
    raw_url = settings.test_database_url
    if not raw_url:
        raise SystemExit("TEST_DATABASE_URL is required for retained account backfill")
    target = make_url(raw_url)
    application = make_url(settings.database_url)
    if not target.database or not target.database.endswith("_test") or target == application:
        raise SystemExit("Refusing account backfill outside a separate *_test database")
    engine = create_engine(raw_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        backfill = backfill_rrc_operator_memberships(session)
    generation = rebuild(factory)
    print(json.dumps({"backfill": backfill, "browse_rebuild": generation}, default=str))
    engine.dispose()
    return 0 if generation.get("status") == "published" else 1


if __name__ == "__main__":
    sys.exit(main())
