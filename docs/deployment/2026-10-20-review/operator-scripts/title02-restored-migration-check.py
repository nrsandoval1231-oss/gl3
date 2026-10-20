"""Verify the title migration on a retained GL3 backup, entirely network-isolated."""
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

pg = 'gridlens-map-publication-test-db'
database = 'title02_retained_migration_20261019'
pgroot = Path('/opt/gridlens/performance/map-publication-20261019')
source = Path('/opt/gridlens/releases/title02-test-b22f936ffb55')
image = 'sha256:fd9f8d786b37a2a8e6afcfd0526443fb43310e2875623b8431efa8cda7bae628'
backup = Path('/opt/gridlens/backups/pre-pr88-85acc0eca4db-20261019T223913Z.dump')
expected = '2797dfe19e33d2e86d51c74355160354c28e18b628d4528a89e91c50d17ee915'
assert hashlib.sha256(backup.read_bytes()).hexdigest() == expected
info = json.loads(subprocess.check_output(['docker', 'inspect', pg], text=True))[0]
assert info['HostConfig']['NetworkMode'] == 'none' and not info['State']['Running']
assert any(m['Source'] == str(pgroot/'pgdata') for m in info['Mounts'])
assert (source/'backend/migrations/versions/0032_power_need_titles.py').is_file()

def query(sql, db=database):
    return subprocess.check_output(['docker', 'exec', pg, 'psql', '-h', '/isolated-pg',
        '-U', 'postgres', '-d', db, '-X', '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql], text=True).strip()

def state():
    tables = query("SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename NOT LIKE 'browse_%' AND tablename NOT IN "
        "('alembic_version','power_need_titles','power_need_title_versions') ORDER BY tablename").splitlines()
    result = {}
    for table in tables:
        assert re.fullmatch('[a-z_]+', table)
        result[table] = query("SELECT count(*)::text || ':' || md5(coalesce(string_agg(md5(row_to_json(t)::text),'' "
            "ORDER BY md5(row_to_json(t)::text)),'')) FROM " + table + ' t')
    return result

report = {'started_at': datetime.now(UTC).isoformat(), 'backup_sha256': expected,
          'source_backend_candidate': 'b22f936ffb550dea45d2fa54f76f9983a90f9a782582adc6846bb9ffa35413fa',
          'network': 'none', 'live_database_access': False, 'provider_calls': 0}
try:
    subprocess.run(['docker', 'start', pg], check=True, stdout=subprocess.DEVNULL)
    for _ in range(30):
        if subprocess.run(['docker', 'exec', pg, 'pg_isready', '-h', '/isolated-pg', '-U', 'postgres'], stdout=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Isolated PostgreSQL did not become ready')
    assert query("SELECT count(*) FROM pg_database WHERE datname='"+database+"'", 'postgres') == '0'
    subprocess.run(['docker', 'exec', pg, 'createdb', '-h', '/isolated-pg', '-U', 'postgres', database], check=True)
    with backup.open('rb') as incoming:
        subprocess.run(['docker', 'exec', '-i', pg, 'pg_restore', '-h', '/isolated-pg', '-U', 'postgres',
            '-d', database, '--no-owner', '--no-acl', '--exit-on-error'], stdin=incoming, check=True)
    before = state()
    report['before_schema'] = query('SELECT version_num FROM alembic_version')
    env = {'DATABASE_URL': f'postgresql+psycopg://postgres@/{database}?host=/isolated-pg',
           'APP_PASSWORD_HASH': 'synthetic-migration-only', 'SESSION_SECRET': 'no-http-service',
           'PYTHONPATH': '/workspace/backend/src', 'PYTHONDONTWRITEBYTECODE': '1',
           'INTELLIGENCE_ENABLED': 'false', 'JEV_ENABLED': 'false', 'POWER_NEED_TITLES_ENABLED': 'false',
           'OPENAI_API_KEY': '', 'TYPESAFE_API_KEY': '', 'FIRECRAWL_API_KEY': ''}
    command = ['docker','run','--rm','--network','none','--cpus','1','--memory','2g',
               '-w','/workspace/backend','-v',str(pgroot/'socket')+':/isolated-pg',
               '-v',str(source)+':/workspace:ro']
    for key in env:
        command += ['-e',key]
    command += [image, '/app/backend/.venv/bin/alembic']
    for arguments in (['upgrade','head'], ['upgrade','head'], ['check']):
        subprocess.run(command + arguments, env={**os.environ, **env}, check=True, timeout=180)
    after = state()
    assert before == after, 'Existing canonical rows changed during migration'
    assert query('SELECT count(*) FROM power_need_titles') == '0'
    assert query('SELECT count(*) FROM power_need_title_versions') == '0'
    report.update(passed=True, canonical_tables_preserved=len(before), after_schema=query('SELECT version_num FROM alembic_version'),
                  title_tables_empty=True, migration_repeat_passed=True, schema_parity_passed=True,
                  preserved_state_digest=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest())
finally:
    subprocess.run(['docker', 'stop', '--timeout', '15', pg], check=True, stdout=subprocess.DEVNULL)
    report.update(finished_at=datetime.now(UTC).isoformat(), isolated_database_stopped=True)
    print(json.dumps(report), flush=True)
