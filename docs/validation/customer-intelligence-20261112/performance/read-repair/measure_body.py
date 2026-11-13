"""Supplement root's unchanged read-only latency harness with exact JSON byte sizes."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Refusing to overwrite receipt')
sys.path.insert(0, str(args.source_root / 'backend/src'))
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from gridlens.intelligence.customer_results import groups
from gridlens.persistence.database import SessionLocal, engine
from gridlens.settings import settings
url = make_url(settings.database_url)
allowed = {'commercial_rollup_scale_perf_base_test', 'commercial_rollup_scale_perf_repair_test'}
if url.database not in allowed or url.host not in {'localhost', '127.0.0.1', '::1'} or url.port != 55439 or url.query:
    raise SystemExit('Outside task-owned loopback database allowlist')
queries = [0]
@event.listens_for(engine, 'before_cursor_execute')
def count(*_):
    queries[0] += 1
results = {}
for limit in (1,25,50):
    with SessionLocal() as session:
        session.execute(text('SET TRANSACTION READ ONLY'))
        queries[0] = 0
        result = groups(session, limit=limit)
        results[str(limit)] = {'json_utf8_bytes': len(json.dumps(result, default=str, separators=(',',':')).encode()),
                               'sql_statements': queries[0], 'returned_groups': len(result['items']), 'account_total': result['total']}
with SessionLocal() as session:
    session.execute(text('SET TRANSACTION READ ONLY'))
    budgets = dict(session.execute(text('SELECT (SELECT count(*) FROM logical_calls) AS logical_calls, (SELECT count(*) FROM logical_call_budgets) AS logical_call_budgets, (SELECT count(*) FROM logical_call_settlements) AS logical_call_settlements')).mappings().one())
receipt = {'page_sizes': results, 'provider_ledger_rows': budgets, 'encoding': 'Compact JSON UTF-8, default=str; excludes HTTP headers, compression and transport'}
args.output.write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt))
