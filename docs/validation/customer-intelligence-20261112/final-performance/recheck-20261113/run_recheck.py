"""Fresh same-day baseline and optimized local performance recheck.

Only the explicitly listed *_test loopback databases are used. Existing receipts
and databases are retained; new ingestion databases are disposable and created
by the synthetic benchmark, and the optimized rollup database is new and seeded
with the shared synthetic 40k corpus.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import argparse
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path('/workspace/gl3-commercial')
BASE = Path('/workspace/gl3-mission-baseline-5ee2f30c')
OUTPUT = Path(__file__).resolve().parent
DBS = {
    'ingestion_base': 'gl3_mission_ingest_recheck_base_test',
    'ingestion_candidate': 'gl3_mission_ingest_recheck_candidate_test',
    'rollup_base': 'gl3_mission_rollup_scale_base_test',
    'rollup_candidate': 'gl3_mission_rollup_scale_recheck_candidate_test',
}
ROLLUP_ROWS = 40_000


def stamp():
    return datetime.now(UTC).isoformat()


def source_manifest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / 'backend/src').rglob('*.py')):
        digest.update(str(path.relative_to(root / 'backend/src')).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_url(db: str):
    if db not in DBS.values() or not db.endswith('_test'):
        raise RuntimeError('Database outside fixed task-owned *_test allowlist')
    raw = os.environ.get('DATABASE_URL')
    if not raw:
        raise RuntimeError('DATABASE_URL is not set')
    url = make_url(raw).set(database=db)
    if url.host not in {'127.0.0.1', 'localhost', '::1'} or url.port != 55439 or url.query:
        raise RuntimeError('Requires exact loopback PostgreSQL port 55439 without query overrides')
    return url


def sanitized(value: str) -> str:
    raw = os.environ.get('DATABASE_URL', '')
    if raw:
        value = value.replace(raw, '<database-url-redacted>')
        password = make_url(raw).password
        if password:
            value = value.replace(password, '<credential-redacted>')
    return value


def run(name: str, args: list[str], *, cwd: Path, env: dict[str, str]) -> dict:
    logfile = OUTPUT / f'{name}.log'
    if logfile.exists():
        raise RuntimeError(f'Refusing to overwrite {logfile.name}')
    started, clock = stamp(), perf_counter()
    child = subprocess.run(args, cwd=cwd, env=env, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logfile.write_text(sanitized(child.stdout), encoding='utf-8')
    record = {'label': name, 'started_at': started, 'finished_at': stamp(),
              'wall_seconds': round(perf_counter() - clock, 3),
              'exit_code': child.returncode, 'log_file': logfile.name,
              'log_sha256': sha(logfile)}
    if child.returncode:
        raise RuntimeError(f'{name} failed; see sanitized {logfile.name}')
    return record


def database_counts(url) -> dict:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return dict(connection.execute(text('''
                SELECT (SELECT count(*) FROM projects) AS projects,
                       (SELECT count(*) FROM power_needs) AS needs,
                       (SELECT count(*) FROM evidence) AS evidence,
                       (SELECT count(*) FROM company_identities) AS companies,
                       (SELECT count(*) FROM logical_calls) AS logical_calls,
                       (SELECT count(*) FROM logical_call_budgets) AS logical_call_budgets,
                       (SELECT count(*) FROM logical_call_settlements) AS logical_call_settlements
            ''' )).mappings().one())
    finally:
        engine.dispose()


def fresh_database(url) -> None:
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as connection:
            exists = connection.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'),
                                        {'name': url.database}).first()
            if exists:
                raise RuntimeError(f'Refusing to destroy preexisting database {url.database}')
            connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


def check_existing_rollup(url) -> None:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            counts = connection.execute(text('''
                SELECT (SELECT count(*) FROM projects) AS projects,
                       (SELECT count(*) FROM power_needs) AS needs,
                       (SELECT count(*) FROM evidence) AS evidence
            ''' )).mappings().one()
            if tuple(counts.values()) != (40_000, 48, 48):
                raise RuntimeError(f'Existing baseline rollup corpus unexpected: {dict(counts)}')
    finally:
        engine.dispose()


def run_ingestion(side: str, root: Path, metadata: dict) -> dict:
    name = f'ingestion_{side}'
    db = DBS[name]
    url = checked_url(db)
    before = source_manifest(root)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if side == 'base' and not commit.startswith('5ee2f30c'):
        raise RuntimeError(f'Wrong baseline commit: {commit}')
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root / 'backend/src')
    env['WORKER_AUTO_REFRESH'] = 'false'
    env['INTELLIGENCE_ENABLED'] = 'false'
    env['DATABASE_URL'] = url.render_as_string(hide_password=False)
    script = root / 'scripts/ingestion_write_benchmark.py'
    result = run(name, [sys.executable, str(script), '--database-url',
                        url.render_as_string(hide_password=False), '--projects', '5000',
                        '--records', '300', '--json-out', str(OUTPUT / f'{name}.json')],
                 cwd=root / 'backend', env=env)
    after = source_manifest(root)
    metadata['ingestion'][side] = {
        **result, 'source_commit': commit, 'source_manifest_sha256_before': before,
        'source_manifest_sha256_after': after, 'source_unchanged_during_run': before == after,
        'database': db, 'benchmark_harness_sha256': sha(script),
        'corpus_counts_after': database_counts(url),
    }
    metadata['ingestion'][side]['result_sha256'] = sha(OUTPUT / f'{name}.json')
    return metadata['ingestion'][side]


def run_rollup(side: str, root: Path, metadata: dict, *, fresh: bool) -> dict:
    name = f'rollup_{side}'
    db = DBS[name]
    url = checked_url(db)
    if fresh:
        fresh_database(url)
    else:
        check_existing_rollup(url)
    before = source_manifest(root)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root / 'backend/src')
    env['WORKER_AUTO_REFRESH'] = 'false'
    env['INTELLIGENCE_ENABLED'] = 'false'
    env['DATABASE_URL'] = url.render_as_string(hide_password=False)
    operations = []
    if fresh:
        operations.append(run(f'{name}_migrate', [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                              cwd=root / 'backend', env=env))
        seeder = root / 'web/acceptance/rollup-scale/seed.py'
        operations.append(run(f'{name}_seed', [sys.executable, str(seeder), '--rows',
                              str(ROLLUP_ROWS), '--manifest-output',
                              str(OUTPUT / f'{name}_seed.json')], cwd=root / 'backend', env=env))
    measure = ROOT / 'scripts/benchmark_customer_commercial.py'
    operations.append(run(f'{name}_measure', [sys.executable, str(measure), '--source-root',
                          str(root), '--output', str(OUTPUT / f'{name}.json'), '--samples', '10'],
                          cwd=ROOT / 'backend', env=env))
    after = source_manifest(root)
    metadata['rollup'][side] = {
        'source_commit': commit, 'source_manifest_sha256_before': before,
        'source_manifest_sha256_after': after, 'source_unchanged_during_run': before == after,
        'database': db, 'database_counts': database_counts(url),
        'fresh_database_and_seeded': fresh, 'operations': operations,
        'result_sha256': sha(OUTPUT / f'{name}.json'),
        'measure_harness_sha256': sha(measure),
        'transaction_context': 'read-only, 15s timeout, SET LOCAL jit = off',
    }
    return metadata['rollup'][side]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollup-only', action='store_true')
    args = parser.parse_args()
    receipt = OUTPUT / ('rollup_recheck_metadata.json' if args.rollup_only else 'metadata.json')
    if receipt.exists():
        raise RuntimeError('Refusing to overwrite prior recheck metadata')
    metadata = {
        'started_at': stamp(),
        'postgres_version': None,
        'python_version': sys.version.split()[0],
        'runtime_dependencies': {name: importlib.metadata.version(name)
                                 for name in ('sqlalchemy', 'beautifulsoup4', 'soupsieve', 'psycopg')},
        'database_host': '127.0.0.1:55439',
        'database_names': DBS,
        'ingestion': {}, 'rollup': {},
        'limitations': ['Synthetic local fixtures only; no external or paid provider execution.',
                        'Ingestion runs are same-day and each uses a newly created *_test database.',
                        'Baseline rollup is a read-only repeat on the prior 40k synthetic corpus; optimized rollup uses a new fresh 40k synthetic corpus.',
                        'Timings are local single recheck runs, not a production SLA.'],
    }
    probe = create_engine(checked_url(DBS['ingestion_base']).set(database='postgres'))
    try:
        with probe.connect() as connection:
            metadata['postgres_version'] = connection.execute(text('SELECT version()')).scalar_one()
    finally:
        probe.dispose()
    if not args.rollup_only:
        run_ingestion('base', BASE, metadata)
        run_ingestion('candidate', ROOT, metadata)
    run_rollup('base', BASE, metadata, fresh=False)
    run_rollup('candidate', ROOT, metadata, fresh=True)
    metadata['finished_at'] = stamp()
    receipt.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
