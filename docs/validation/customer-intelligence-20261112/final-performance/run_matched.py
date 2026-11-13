"""Matched local performance run on new, disposable customer-intelligence databases.

Run with the private task environment already loaded. No URLs or credentials are
written to receipts. Each lane has a fixed database allowlist and refuses to reuse
an existing rollup database or receipt path.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path('/workspace/gl3-commercial')
BASE = Path('/workspace/gl3-mission-baseline-5ee2f30c')
OUTPUT = ROOT / 'docs/validation/customer-intelligence-20261112/final-performance'
NAMES = {
    'base': ('gl3_mission_ingest_base_test', 'gl3_mission_rollup_scale_base_test'),
    'candidate': ('gl3_mission_ingest_candidate_test', 'gl3_mission_rollup_scale_candidate_test'),
}
ROWS = 40_000


def stamp():
    return datetime.now(UTC).isoformat()


def source_manifest(root):
    digest = hashlib.sha256()
    for path in sorted((root / 'backend/src').rglob('*.py')):
        digest.update(str(path.relative_to(root / 'backend/src')).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def url_for(name):
    allowed = {name for pair in NAMES.values() for name in pair}
    if name not in allowed:
        raise RuntimeError('Database outside task-owned allowlist')
    raw = os.environ.get('DATABASE_URL')
    if not raw:
        raise RuntimeError('DATABASE_URL is not set')
    url = make_url(raw).set(database=name)
    if url.host not in {'127.0.0.1', 'localhost', '::1'} or url.port != 55439 or url.query:
        raise RuntimeError('Requires exact loopback PostgreSQL port 55439 without query overrides')
    if not (url.database or '').endswith('_test'):
        raise RuntimeError('Database must end in _test')
    return url


def sanitize(value):
    raw = os.environ.get('DATABASE_URL', '')
    if raw:
        value = value.replace(raw, '<database-url-redacted>')
        password = make_url(raw).password
        if password:
            value = value.replace(password, '<credential-redacted>')
    return value


def run(label, args, *, cwd, env):
    logfile = OUTPUT / f'{label}.log'
    if logfile.exists():
        raise RuntimeError(f'Refusing to overwrite {logfile.name}')
    started = stamp()
    clock = perf_counter()
    child = subprocess.run(args, cwd=cwd, env=env, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logfile.write_text(sanitize(child.stdout), encoding='utf-8')
    record = {'label': label, 'started_at': started, 'finished_at': stamp(),
              'wall_seconds': round(perf_counter() - clock, 3),
              'exit_code': child.returncode, 'log_file': logfile.name,
              'log_sha256': sha(logfile)}
    print(json.dumps(record), flush=True)
    if child.returncode:
        raise RuntimeError(f'{label} failed; inspect sanitized log {logfile.name}')
    return record


def recreate_new_rollup(url):
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as connection:
            exists = connection.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'),
                                        {'name': url.database}).first()
            if exists:
                raise RuntimeError(f'Refusing to destroy existing database {url.database}')
            connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


def main():
    help_text = 'Choose ingestion/rollup base or candidate, or rollup-fixed for an existing seeded database'
    if len(sys.argv) != 2:
        raise RuntimeError(help_text)
    try:
        lane, side = sys.argv[1].rsplit('-', 1)
    except ValueError as error:
        raise RuntimeError(help_text) from error
    if lane not in {'ingestion', 'rollup', 'rollup-fixed'} or side not in {'base', 'candidate'}:
        raise RuntimeError(help_text)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    metadata_path = OUTPUT / f'{lane}-{side}-metadata.json'
    if metadata_path.exists():
        raise RuntimeError(f'Refusing to overwrite {metadata_path.name}')
    metadata = {
        'lane': lane, 'side': side, 'started_at': stamp(), 'postgres_version': None, 'runs': [],
        'python_version': sys.version.split()[0],
        'runtime_dependencies': {
            name: importlib.metadata.version(name)
            for name in ('sqlalchemy', 'beautifulsoup4', 'soupsieve', 'psycopg')
        },
        'limitations': ['Synthetic, disposable local fixtures only.',
                        'No external or paid provider execution.',
                        'Both checkouts use the current shared uv environment; runtime dependency versions are recorded.',
                        'Timings are single-run diagnostics, not a production SLA.'],
    }
    if lane == 'rollup':
        metadata['rollup_rows_requested'] = ROWS
    probe = create_engine(url_for(NAMES['base'][0]).set(database='postgres'))
    try:
        with probe.connect() as connection:
            metadata['postgres_version'] = connection.execute(text('SELECT version()')).scalar_one()
    finally:
        probe.dispose()

    root = BASE if side == 'base' else ROOT
    if not root.is_dir():
        raise RuntimeError(f'Missing source checkout: {root}')
    before = source_manifest(root)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if side == 'base' and not commit.startswith('5ee2f30c'):
        raise RuntimeError(f'Baseline checkout must be 5ee2f30c, got {commit}')
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root / 'backend/src')
    env['WORKER_AUTO_REFRESH'] = 'false'
    env['INTELLIGENCE_ENABLED'] = 'false'
    db = NAMES[side][0 if lane == 'ingestion' else 1]
    url = url_for(db)
    env['DATABASE_URL'] = url.render_as_string(hide_password=False)
    info = {'side': side, 'source_commit': commit,
            'source_manifest_sha256_before': before, 'database': db,
            'commands': []}
    if lane == 'ingestion':
        script = root / 'scripts/ingestion_write_benchmark.py'
        info['harness_sha256'] = sha(script)
        info['commands'].append(run(f'ingestion-{side}', [sys.executable, str(script),
            '--database-url', url.render_as_string(hide_password=False),
            '--projects', '5000', '--records', '300', '--json-out',
            str(OUTPUT / f'ingestion-{side}.json')], cwd=root / 'backend', env=env))
    else:
        if lane == 'rollup':
            recreate_new_rollup(url)
            info['commands'].append(run(f'rollup-migrate-{side}',
                [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                cwd=root / 'backend', env=env))
            seed = root / 'web/acceptance/rollup-scale/seed.py'
            info['seeder_sha256'] = sha(seed)
            info['account_fixture_sha256'] = sha(root / 'web/acceptance/rollup-scale/account_fixture.py')
            info['scale_fixture_sha256'] = sha(root / 'backend/tests/integration/rollup_scale_fixture.py')
            info['commands'].append(run(f'rollup-seed-{side}', [sys.executable, str(seed),
                '--manifest-output', str(OUTPUT / f'rollup-seed-{side}.json'),
                '--rows', str(ROWS)], cwd=root / 'backend', env=env))
        # The common benchmark harness postdates the baseline commit; pin its
        # code to this task's candidate checkout while importing each side's
        # backend source through --source-root.
        measure = ROOT / 'scripts/benchmark_customer_commercial.py'
        info['measure_harness_sha256'] = sha(measure)
        suffix = 'fixed-' if lane == 'rollup-fixed' else ''
        info['measure_context'] = 'SET LOCAL jit = off; read-only transaction'
        info['commands'].append(run(f'rollup-measure-{suffix}{side}', [sys.executable, str(measure),
            '--source-root', str(root), '--output', str(OUTPUT / f'rollup-{suffix}{side}.json'),
            '--samples', '10'], cwd=root / 'backend', env=env))
        body = OUTPUT / 'measure_body_bytes.py'
        info['commands'].append(run(f'rollup-body-{suffix}{side}', [sys.executable, str(body),
            '--source-root', str(root), '--output',
            str(OUTPUT / f'rollup-body-{suffix}{side}.json')], cwd=root / 'backend', env=env))
    after = source_manifest(root)
    info['source_manifest_sha256_after'] = after
    info['source_unchanged_during_run'] = before == after
    metadata['runs'].append(info)
    metadata['updated_at'] = stamp()
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    metadata['finished_at'] = stamp()
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
