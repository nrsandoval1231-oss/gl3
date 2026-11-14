"""Task-owned local matched performance runner; never accepts arbitrary databases.

Run from candidate backend with the task environment already loaded. URLs are
resolved only from process environment and never retained in receipts.
"""
from __future__ import annotations

import hashlib
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
BASE = Path('/workspace/gl3-baseline')
OUTPUT = ROOT / 'docs/validation/customer-intelligence-20261112/performance'
NAMES = {
    'base': ('commercial_ingest_perf_base_test', 'commercial_rollup_scale_perf_base_test'),
    'candidate': ('commercial_ingest_perf_candidate_test', 'commercial_rollup_scale_perf_candidate_test'),
}


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
    if name not in {n for pair in NAMES.values() for n in pair}:
        raise RuntimeError('Database outside task-owned allowlist')
    url = make_url(os.environ['DATABASE_URL']).set(database=name)
    if url.host not in {'127.0.0.1', 'localhost', '::1'} or url.port != 55439 or url.query:
        raise RuntimeError('Requires exact loopback PostgreSQL port 55439 without query overrides')
    return url


def safe(text_value):
    raw = os.environ.get('DATABASE_URL', '')
    if raw:
        text_value = text_value.replace(raw, '<database-url-redacted>')
        password = make_url(raw).password
        if password:
            text_value = text_value.replace(password, '<credential-redacted>')
    return text_value


def run(label, args, *, cwd, env):
    logfile = OUTPUT / f'{label}.log'
    if logfile.exists():
        raise RuntimeError(f'Refusing to overwrite {logfile.name}')
    start = stamp()
    clock = perf_counter()
    child = subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logfile.write_text(safe(child.stdout))
    record = {'label': label, 'started_at': start, 'finished_at': stamp(),
              'wall_seconds': perf_counter() - clock, 'exit_code': child.returncode,
              'log_file': logfile.name, 'log_sha256': sha(logfile)}
    print(json.dumps(record), flush=True)
    if child.returncode:
        raise RuntimeError(f'{label} failed; see sanitized log {logfile.name}')
    return record


def recreate_new_rollup(url):
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        exists = connection.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'), {'name': url.database}).first()
        if exists:
            raise RuntimeError('Rollup target already exists: refusing to destroy a populated database')
        connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


def main():
    lane = sys.argv[1]
    if lane not in {'ingestion', 'rollup'}:
        raise RuntimeError('Choose ingestion or rollup')
    metadata = {'started_at': stamp(), 'postgres_version': None, 'runs': [],
                'limitations': ['Shared machine while root full backend pytest runs with four workers.',
                                'Single matched ingestion run, not a statistical regression gate.',
                                'All sources and accounts are synthetic disposable fixtures.',
                                'No external/provider execution; ingestion retrieval is fixture-monkeypatched.']}
    check = create_engine(url_for(NAMES['base'][0]).set(database='postgres'))
    with check.connect() as connection:
        metadata['postgres_version'] = connection.execute(text('SELECT version()')).scalar_one()
    check.dispose()
    for side, root in [('base', BASE), ('candidate', ROOT)]:
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(root / 'backend/src')
        environment['WORKER_AUTO_REFRESH'] = 'false'
        environment['INTELLIGENCE_ENABLED'] = 'false'
        source_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        before = source_manifest(root)
        db = NAMES[side][0 if lane == 'ingestion' else 1]
        url = url_for(db)
        environment['DATABASE_URL'] = url.render_as_string(hide_password=False)
        info = {'side': side, 'source_commit': source_sha, 'source_manifest_sha256_before': before,
                'database': db, 'commands': []}
        if lane == 'ingestion':
            script = root / 'scripts/ingestion_write_benchmark.py'
            info['harness_sha256'] = sha(script)
            info['commands'].append(run(f'ingestion-{side}', [sys.executable, str(script), '--database-url',
                url.render_as_string(hide_password=False), '--projects', '5000', '--records', '300',
                '--json-out', str(OUTPUT / f'ingestion-{side}.json')], cwd=root / 'backend', env=environment))
        else:
            recreate_new_rollup(url)
            info['commands'].append(run(f'rollup-migrate-{side}', [sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=root / 'backend', env=environment))
            seed = root / 'web/acceptance/rollup-scale/seed.py'
            info['seeder_sha256'] = sha(seed)
            info['account_fixture_sha256'] = sha(root / 'web/acceptance/rollup-scale/account_fixture.py')
            info['scale_fixture_sha256'] = sha(root / 'backend/tests/integration/rollup_scale_fixture.py')
            info['commands'].append(run(f'rollup-seed-{side}', [sys.executable, str(seed), '--manifest-output', str(OUTPUT / f'rollup-seed-{side}.json'), '--rows', '2098'], cwd=root / 'backend', env=environment))
            measure = ROOT / 'scripts/benchmark_customer_commercial.py'
            info['measure_harness_sha256'] = sha(measure)
            info['commands'].append(run(f'rollup-measure-{side}', [sys.executable, str(measure), '--source-root', str(root), '--output', str(OUTPUT / f'rollup-{side}.json'), '--samples', '10'], cwd=root / 'backend', env=environment))
            body = OUTPUT / 'measure_body_bytes.py'
            info['commands'].append(run(f'rollup-body-{side}', [sys.executable, str(body), '--source-root', str(root), '--output', str(OUTPUT / f'rollup-body-{side}.json')], cwd=root / 'backend', env=environment))
        info['source_manifest_sha256_after'] = source_manifest(root)
        info['source_unchanged_during_run'] = before == info['source_manifest_sha256_after']
        metadata['runs'].append(info)
        (OUTPUT / f'{lane}-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    metadata['finished_at'] = stamp()
    (OUTPUT / f'{lane}-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')


if __name__ == '__main__':
    main()
