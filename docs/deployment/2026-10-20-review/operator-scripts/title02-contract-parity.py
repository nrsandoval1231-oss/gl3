"""Read-only API contract comparison with unavailable database and no provider keys."""
import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent / 'gl3-title-enrichment'
sys.path.insert(0, str(root/'backend/src'))
os.environ.update(DATABASE_URL='postgresql+psycopg://unavailable:unavailable@127.0.0.1/unavailable',
                  APP_PASSWORD_HASH='non-authenticating-contract-only', SESSION_SECRET='contract-check-no-http',
                  OPENAI_API_KEY='', TYPESAFE_API_KEY='', FIRECRAWL_API_KEY='',
                  INTELLIGENCE_ENABLED='false', JEV_ENABLED='false', POWER_NEED_TITLES_ENABLED='false')
from gridlens.api.app import app

contract = root/'web/src/api/openapi.json'
assert json.loads(contract.read_text(encoding='utf-8')) == app.openapi(), 'API schema differs from exported contract'
print(json.dumps({'openapi_parity': True, 'contract_sha256': hashlib.sha256(contract.read_bytes()).hexdigest(),
                  'database_queries': 0, 'provider_calls': 0}))
