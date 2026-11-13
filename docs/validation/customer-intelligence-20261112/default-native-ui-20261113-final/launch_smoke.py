from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(os.environ.get('GRIDLENS_SOURCE_ROOT', str(Path(__file__).resolve().parents[4])))
seed = json.loads(Path(os.environ.get('GRIDLENS_SMOKE_MANIFEST', '/workspace/task-runtime/retained_ui_smoke_seed_replay.json')).read_text())
target = make_url(os.environ['TEST_DATABASE_URL']).set(database=seed['database_name'])
if target.host not in {'127.0.0.1', 'localhost', '::1'} or not target.database or not target.database.startswith('gl3_retained_ui_smoke_') or not target.database.endswith('_test'):
    raise RuntimeError('Only an isolated, seed-created loopback smoke test database is allowed')
ports = (18491, 15491)
for port in ports:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Required smoke port {port} is already occupied') from exc

api_env = os.environ.copy()
api_env['DATABASE_URL'] = target.render_as_string(hide_password=False)
api_env['SAVED_BROWSE_ENABLED'] = 'true'
api_env['COOKIE_SECURE'] = 'false'
api_env['TRUSTED_ORIGINS'] = 'http://127.0.0.1:15491,http://127.0.0.1:15490'
web_env = os.environ.copy()
web_env['GRIDLENS_API_PORT'] = '18491'
for key in ('OPENAI_API_KEY', 'FIRECRAWL_API_KEY', 'TYPESAFE_API_KEY'):
    api_env[key] = ''
api_env['WORKER_AUTO_REFRESH'] = 'false'
logs = Path(os.environ.get('GRIDLENS_SMOKE_RUNTIME_DIR', '/workspace/task-runtime/retained-smoke-replay'))
logs.mkdir(parents=True, exist_ok=False)
api_log = (logs / 'retained-ui-smoke-api.log').open('w')
web_log = (logs / 'retained-ui-smoke-web.log').open('w')
api = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'gridlens.api.app:app', '--host', '127.0.0.1', '--port', '18491'],
    cwd=ROOT / 'backend',
    env=api_env,
    stdin=subprocess.DEVNULL,
    stdout=api_log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
web = None
try:
    api_url = 'http://127.0.0.1:18491'
    web_url = 'http://127.0.0.1:15491'
    ready = False
    for _ in range(60):
        if api.poll() is not None:
            raise RuntimeError('API exited during startup; see private task-runtime log')
        try:
            urlopen(api_url + '/api/health', timeout=1)
        except Exception as exc:
            if getattr(exc, 'code', None) not in {401, 403}:
                time.sleep(0.5)
                continue
        ready = True
        break
    if not ready:
        raise RuntimeError('API did not become ready; see private task-runtime log')
    web = subprocess.Popen(
        ['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '15491', '--strictPort'],
        cwd=ROOT / 'web',
        env=web_env,
        stdin=subprocess.DEVNULL,
        stdout=web_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    ui_ready = False
    for _ in range(60):
        if web.poll() is not None:
            raise RuntimeError('Vite exited during startup; see private task-runtime log')
        try:
            with urlopen(web_url, timeout=1) as response:
                if response.status == 200:
                    ui_ready = True
                    break
        except Exception:
            time.sleep(0.5)
    if not ui_ready:
        raise RuntimeError('Vite did not become ready; see private task-runtime log')
    audit = create_engine(target)
    try:
        with audit.begin() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            logical_calls = connection.scalar(text('SELECT count(*) FROM logical_calls'))
    finally:
        audit.dispose()
    result = {
        'database_name': seed['database_name'],
        'database_host': seed['database_host'],
        'database_port': seed['database_port'],
        'api_url': api_url,
        'api_port': 18491,
        'api_pid': api.pid,
        'ui_url': web_url,
        'ui_port': 15491,
        'ui_pid': web.pid,
        'api_readiness': 'health route responds with auth required',
        'ui_readiness': 'HTTP 200',
        'saved_browse_enabled': True,
        'logical_provider_calls': logical_calls,
        'logs': [str(logs / 'retained-ui-smoke-api.log'), str(logs / 'retained-ui-smoke-web.log')],
    }
    (logs / 'servers.json').write_text(
        json.dumps(result, indent=2, sort_keys=True) + '\n'
    )
    print(json.dumps(result, sort_keys=True))
except Exception:
    if web is not None:
        web.terminate()
    api.terminate()
    raise
finally:
    api_log.close()
    web_log.close()
