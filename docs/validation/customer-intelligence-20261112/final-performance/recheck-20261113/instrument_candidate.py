"""One instrumented reproduction of the optimized synthetic ingestion lane."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path('/workspace/gl3-commercial')
OUT = Path(__file__).resolve().parent
DB = 'gl3_mission_ingest_repro_candidate_test'
APP = 'gl3_ingest_repro_observer'


def stamp():
    return datetime.now(UTC).isoformat()


def manifest(root: Path) -> str:
    digest = hashlib.sha256()
    source = root / 'backend/src'
    for path in sorted(source.rglob('*.py')):
        digest.update(str(path.relative_to(source)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def sample_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding='utf-8').strip()
    except (OSError, UnicodeDecodeError):
        return None


def host_pressure() -> dict:
    return {
        'loadavg': sample_file('/proc/loadavg'),
        'cpu_pressure': sample_file('/proc/pressure/cpu'),
        'io_pressure': sample_file('/proc/pressure/io'),
        'cpu_cgroup': sample_file('/sys/fs/cgroup/cpu.stat'),
        'io_cgroup': sample_file('/sys/fs/cgroup/io.stat'),
    }


def write_json_line(path: Path, value: dict) -> None:
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, default=str) + '\n')
        stream.flush()


def main() -> None:
    url_raw = os.environ.get('DATABASE_URL')
    if not url_raw:
        raise RuntimeError('DATABASE_URL is not set')
    url = make_url(url_raw).set(database=DB)
    if (url.database != DB or not DB.endswith('_test')
            or url.host not in {'127.0.0.1', 'localhost', '::1'}
            or url.port != 55439 or url.query):
        raise RuntimeError('Requires the fixed loopback *_test database and port 55439')
    monitor_path = OUT / 'candidate_observer.jsonl'
    host_path = OUT / 'candidate_host_pressure.jsonl'
    log_path = OUT / 'candidate_instrumented.log'
    receipt_path = OUT / 'candidate_instrumented.json'
    for path in (monitor_path, host_path, log_path, receipt_path):
        if path.exists():
            raise RuntimeError(f'Refusing to overwrite {path.name}')
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as connection:
            exists = connection.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'),
                                        {'name': DB}).first()
            if exists:
                raise RuntimeError(f'Refusing to use preexisting database {DB}')
    finally:
        admin.dispose()

    env = dict(os.environ)
    env['DATABASE_URL'] = url.render_as_string(hide_password=False)
    env['PYTHONPATH'] = str(ROOT / 'backend/src')
    env['WORKER_AUTO_REFRESH'] = 'false'
    env['INTELLIGENCE_ENABLED'] = 'false'
    env['PGAPPNAME'] = APP
    observer_engine = create_engine(
        url.set(database='postgres'), pool_size=1, max_overflow=0,
        connect_args={'connect_timeout': 2},
    )
    done = threading.Event()
    monitor_errors: list[str] = []

    def monitor() -> None:
        query = text('''
            SELECT pid, state, wait_event_type, wait_event,
                   clock_timestamp() - query_start AS query_age,
                   pg_blocking_pids(pid) AS blocking_pids,
                   left(query, 1000) AS query
            FROM pg_stat_activity
            WHERE datname = :db AND application_name = :app AND pid <> pg_backend_pid()
            ORDER BY pid
        ''')
        while not done.is_set():
            started = time.monotonic()
            try:
                with observer_engine.connect() as connection:
                    rows = connection.execute(query, {'db': DB, 'app': APP}).mappings().all()
                sampled = stamp()
                for row in rows:
                    write_json_line(monitor_path, {'observed_at': sampled, **dict(row)})
                write_json_line(host_path, {'observed_at': sampled, **host_pressure()})
            except Exception as error:  # retain diagnostic monitor failures explicitly
                monitor_errors.append(f'{type(error).__name__}: {error}')
            done.wait(max(0.01, 0.15 - (time.monotonic() - started)))

    before = manifest(ROOT)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    metadata = {
        'started_at': stamp(), 'database': DB, 'source_commit': commit,
        'source_manifest_sha256_before': before,
        'benchmark_script_sha256': hashlib.sha256(
            (ROOT / 'scripts/ingestion_write_benchmark.py').read_bytes()
        ).hexdigest(),
        'monitor_interval_seconds': 0.15,
        'statement_timeout': 'unchanged application SET LOCAL 2500ms on acquisition transaction',
        'host_pressure_before': host_pressure(),
        'result_file_expected': 'candidate_instrumented.json',
    }
    thread = threading.Thread(target=monitor, name='candidate-db-observer', daemon=True)
    thread.start()
    command = [sys.executable, str(ROOT / 'scripts/ingestion_write_benchmark.py'),
               '--database-url', url.render_as_string(hide_password=False),
               '--projects', '5000', '--records', '300', '--json-out', str(receipt_path)]
    started, clock = stamp(), time.perf_counter()
    try:
        child = subprocess.run(command, cwd=ROOT / 'backend', env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    finally:
        done.set()
        thread.join(timeout=5)
        observer_engine.dispose()
    output = child.stdout.replace(url_raw, '<database-url-redacted>')
    if url.password:
        output = output.replace(url.password, '<credential-redacted>')
    log_path.write_text(output, encoding='utf-8')
    metadata.update({
        'finished_at': stamp(), 'wall_seconds': round(time.perf_counter() - clock, 3),
        'exit_code': child.returncode, 'log_sha256': hashlib.sha256(log_path.read_bytes()).hexdigest(),
        'observer_samples': sum(1 for _ in monitor_path.open(encoding='utf-8')) if monitor_path.exists() else 0,
        'host_pressure_samples': sum(1 for _ in host_path.open(encoding='utf-8')) if host_path.exists() else 0,
        'observer_errors': monitor_errors, 'host_pressure_after': host_pressure(),
        'source_manifest_sha256_after': manifest(ROOT),
        'source_unchanged_during_run': before == manifest(ROOT),
        'result_exists': receipt_path.exists(),
    })
    (OUT / 'candidate_instrumented_metadata.json').write_text(
        json.dumps(metadata, indent=2) + '\n', encoding='utf-8'
    )
    print(json.dumps({key: metadata[key] for key in (
        'database', 'source_commit', 'wall_seconds', 'exit_code',
        'observer_samples', 'host_pressure_samples', 'source_unchanged_during_run',
        'result_exists',
    )}, indent=2))
    if child.returncode:
        raise SystemExit(child.returncode)


if __name__ == '__main__':
    main()
