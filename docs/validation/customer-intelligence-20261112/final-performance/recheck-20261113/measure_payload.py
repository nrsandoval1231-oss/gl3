"""Read-only compact JSON bytes and provider ledger counts for recheck corpora."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path('/workspace/gl3-commercial')
BASE = Path('/workspace/gl3-mission-baseline-5ee2f30c')
DBS = {
    'base': 'gl3_mission_rollup_scale_base_test',
    'candidate': 'gl3_mission_rollup_scale_recheck_candidate_test',
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--side', choices=tuple(DBS), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite payload receipt')
    source_root = BASE if args.side == 'base' else ROOT
    url_raw = os.environ.get('DATABASE_URL')
    if not url_raw:
        raise SystemExit('DATABASE_URL is not set')
    url = make_url(url_raw).set(database=DBS[args.side])
    if (url.host not in {'127.0.0.1', 'localhost', '::1'} or url.port != 55439
            or url.query or not url.database.endswith('_test')):
        raise SystemExit('Outside fixed loopback *_test allowlist')
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    sys.path.insert(0, str(source_root / 'backend/src'))
    from sqlalchemy import text

    from gridlens.intelligence.customer_results import groups
    from gridlens.persistence.database import SessionLocal

    digest = hashlib.sha256()
    source = source_root / 'backend/src'
    for path in sorted(source.rglob('*.py')):
        digest.update(str(path.relative_to(source)).encode())
        digest.update(path.read_bytes())
    results = {}
    for page_size in (1, 25, 50):
        with SessionLocal() as session:
            session.execute(text('SET TRANSACTION READ ONLY'))
            session.execute(text("SET LOCAL statement_timeout = '15s'"))
            session.execute(text('SET LOCAL jit = off'))
            result = groups(session, limit=page_size)
            results[str(page_size)] = {
                'payload_utf8_bytes': len(
                    json.dumps(result, default=str, separators=(',', ':')).encode()
                ),
                'returned_groups': len(result['items']),
                'account_total': result['total'],
            }
    with SessionLocal() as session:
        session.execute(text('SET TRANSACTION READ ONLY'))
        ledgers = dict(session.execute(text('''
            SELECT (SELECT count(*) FROM logical_calls) AS logical_calls,
                   (SELECT count(*) FROM logical_call_budgets) AS logical_call_budgets,
                   (SELECT count(*) FROM logical_call_settlements) AS logical_call_settlements
        ''')).mappings().one())
    receipt = {
        'side': args.side,
        'database': DBS[args.side],
        'source_manifest_sha256': digest.hexdigest(),
        'transaction_context': 'read-only, 15s timeout, SET LOCAL jit = off',
        'page_sizes': results,
        'provider_ledger_rows': ledgers,
        'encoding': 'Compact JSON UTF-8; excludes HTTP headers, compression and transport.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
