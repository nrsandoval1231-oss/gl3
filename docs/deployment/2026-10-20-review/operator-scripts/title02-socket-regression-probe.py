"""Isolate the migration-test socket override without touching the full-run DB."""
import json
import os
import subprocess
from pathlib import Path

pg = 'gridlens-map-publication-test-db'
state = json.loads(subprocess.check_output(['docker', 'inspect', pg], text=True))[0]
assert state['State']['Running'] and state['HostConfig']['NetworkMode'] == 'none'
database = 'title02_socket_probe_test'
exists = subprocess.check_output(['docker', 'exec', pg, 'psql', '-h', '/isolated-pg', '-U', 'postgres',
    '-d', 'postgres', '-X', '-At', '-c', "SELECT count(*) FROM pg_database WHERE datname='" + database + "'"], text=True).strip()
assert exists == '0'
subprocess.run(['docker', 'exec', pg, 'createdb', '-h', '/isolated-pg', '-U', 'postgres', database], check=True)
environment = {
    'DATABASE_URL': 'postgresql+psycopg://postgres@/title02_8f5d19165ab5_app?host=/isolated-pg',
    'TEST_DATABASE_URL': 'postgresql+psycopg://postgres@/' + database + '?host=/isolated-pg',
    'APP_PASSWORD_HASH': 'non-authenticating-probe-only', 'SESSION_SECRET': 'synthetic-probe-only',
    'PYTHONPATH': '/workspace/backend/src', 'PYTHONDONTWRITEBYTECODE': '1',
    'OPENAI_API_KEY': '', 'TYPESAFE_API_KEY': '', 'FIRECRAWL_API_KEY': '',
    'INTELLIGENCE_ENABLED': 'false', 'INTELLIGENCE_MODE': 'disabled',
}
source = Path('/opt/gridlens/releases/title02-test-8f5d19165ab5')
command = ['docker', 'run', '--rm', '--network', 'none', '--cpus', '1', '--memory', '1g',
    '-v', '/opt/gridlens/performance/map-publication-20261019/socket:/isolated-pg',
    '-v', str(source) + ':/workspace:ro', '-w', '/workspace/backend']
for key in environment:
    command += ['-e', key]
test = ['sha256:fd9f8d786b37a2a8e6afcfd0526443fb43310e2875623b8431efa8cda7bae628',
    '/app/backend/.venv/bin/pytest', '-q', '--tb=short', '-o', 'cache_dir=/tmp/pytest-cache',
    'tests/integration/test_logical_calls.py::test_0028_database_trigger_rejects_settlement_edits']
outcomes = []
for configured in (False, True):
    run = subprocess.run(command + (['-e', 'PGHOST=/isolated-pg'] if configured else []) + test,
                         env={**os.environ, **environment}, capture_output=True, text=True, timeout=120)
    (source / ('socket-probe-' + str(configured).lower() + '.log')).write_text(run.stdout + run.stderr)
    print(json.dumps({'PGHOST_configured': configured, 'exit_code': run.returncode,
                      'output': (run.stdout + run.stderr)[-6500:]}), flush=True)
    outcomes.append({'PGHOST_configured': configured, 'exit_code': run.returncode})
assert [result['exit_code'] for result in outcomes] == [1, 0]
print(json.dumps({'diagnosis': 'test_replaces_URL_query_dropping_socket_host', 'confirmed': True,
                  'product_changes': False, 'test_source_changes': False, 'network': 'none',
                  'production_database_access': False, 'outcomes': outcomes}), flush=True)
