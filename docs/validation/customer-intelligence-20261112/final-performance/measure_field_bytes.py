"""Profile per-field compact JSON bytes on one synthetic rollup page."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--limit', type=int, default=25)
parser.add_argument('--database', required=True, choices=(
    'gl3_mission_rollup_scale_base_test',
    'gl3_mission_rollup_scale_candidate_test',
))
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Refusing to overwrite receipt')
if args.limit not in {1, 25, 50}:
    parser.error('limit must be 1, 25, or 50')
base_url = os.environ.get('DATABASE_URL')
if not base_url:
    raise SystemExit('DATABASE_URL is not set')
os.environ['DATABASE_URL'] = make_url(base_url).set(database=args.database).render_as_string(
    hide_password=False
)
sys.path.insert(0, str(args.source_root / 'backend/src'))
from sqlalchemy import text

from gridlens.intelligence.customer_results import groups
from gridlens.persistence.database import SessionLocal
from gridlens.settings import settings

url = make_url(settings.database_url)
allowed = {
    'gl3_mission_rollup_scale_base_test',
    'gl3_mission_rollup_scale_candidate_test',
}
if (url.database != args.database or url.database not in allowed or url.host not in {'localhost', '127.0.0.1', '::1'}
        or url.port != 55439 or url.query):
    raise SystemExit('Outside task-owned loopback database allowlist')
source = args.source_root.resolve() / 'backend/src'
digest = hashlib.sha256()
for path in sorted(source.rglob('*.py')):
    digest.update(str(path.relative_to(source)).encode())
    digest.update(path.read_bytes())
with SessionLocal() as session:
    session.execute(text('SET TRANSACTION READ ONLY'))
    session.execute(text("SET LOCAL statement_timeout = '15s'"))
    session.execute(text('SET LOCAL jit = off'))
    result = groups(session, limit=args.limit)
fields = {}
commercial = {}
for item in result['items']:
    for key, value in item.items():
        fields[key] = fields.get(key, 0) + len(
            json.dumps(value, default=str, separators=(',', ':')).encode()
        )
    for key, value in (item.get('commercial_intelligence') or {}).items():
        commercial[key] = commercial.get(key, 0) + len(
            json.dumps(value, default=str, separators=(',', ':')).encode()
        )
receipt = {
    'source_manifest_sha256': digest.hexdigest(),
    'page_size': args.limit,
    'returned_groups': len(result['items']),
    'account_total': result['total'],
    'payload_utf8_bytes': len(json.dumps(result, default=str, separators=(',', ':')).encode()),
    'summed_item_field_utf8_bytes': fields,
    'summed_commercial_intelligence_subfield_utf8_bytes': commercial,
    'limitations': ['Single direct read-only call; summed item fields omit enclosing JSON syntax.'],
}
args.output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps(receipt, indent=2))
