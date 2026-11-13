"""Fresh source-pinned read benchmark; preserves all historical performance receipts.

Uses the prior task-owned baseline corpus read-only and creates a new empty,
source-matched repair corpus. No arbitrary database target is accepted.
"""
from __future__ import annotations

import argparse
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

OUT = Path(__file__).resolve().parent
BASE = Path('/workspace/gl3-baseline')
REPAIR = Path('/workspace/gl3-backend-fix')
HARNESS = Path('/workspace/gl3-commercial/scripts/benchmark_customer_commercial.py')
ALLOWED = {'base':'commercial_rollup_scale_perf_base_test',
           'repair':'commercial_rollup_scale_perf_repair_test'}


def now():
    return datetime.now(UTC).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hash(root):
    result = hashlib.sha256()
    for path in sorted((root/'backend/src').rglob('*.py')):
        result.update(str(path.relative_to(root/'backend/src')).encode())
        result.update(path.read_bytes())
    return result.hexdigest()


def source_status(root):
    return subprocess.check_output(['git','status','--porcelain','--','backend/src'],cwd=root,text=True).strip()


def database(side):
    url = make_url(os.environ['DATABASE_URL']).set(database=ALLOWED[side])
    if url.host not in {'localhost','127.0.0.1','::1'} or url.port != 55439 or url.query:
        raise RuntimeError('Task requires exact loopback port55439 and no routing overrides')
    return url


def sanitize(log):
    raw = os.environ['DATABASE_URL']
    log = log.replace(raw,'<database-url-redacted>')
    password = make_url(raw).password
    return log.replace(password,'<credential-redacted>') if password else log


def run(name,args,*,root,env):
    logfile=OUT/f'{name}.log'
    if logfile.exists():
        raise RuntimeError('Refusing to overwrite existing command receipt')
    started=now();clock=perf_counter()
    result=subprocess.run(args,cwd=root/'backend',env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    logfile.write_text(sanitize(result.stdout))
    receipt={'name':name,'started_at':started,'finished_at':now(),'wall_seconds':perf_counter()-clock,
             'exit_code':result.returncode,'log_file':logfile.name,'log_sha256':digest(logfile)}
    print(json.dumps(receipt),flush=True)
    if result.returncode:
        raise RuntimeError(f'{name} failed; inspect sanitized retained log')
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair-commit',required=True)
    args=parser.parse_args()
    repair_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPAIR,text=True).strip()
    if repair_commit != args.repair_commit or source_status(REPAIR):
        raise RuntimeError('Repair commit differs or has uncommitted application source')
    if (OUT/'metadata.json').exists():
        raise RuntimeError('Prior run exists; refusing overwrite')
    metadata={'started_at':now(),'samples_per_page_size':30,'runs':[],
              'limitations':['Synthetic2098project417group fixture;48underlyingneed/evidence records.',
                             'Shared executor; no controlled production load or SLA claim.',
                             'Direct service calls exclude API transaction-local JIT policy, HTTP, auth, UI and compression.'],
              'process_snapshot_before':subprocess.check_output(['ps','-eo','pid,stat,etime,pcpu,comm'],text=True)}
    for side,root in [('base',BASE),('repair',REPAIR)]:
        before=source_hash(root)
        environment=dict(os.environ)
        url=database(side)
        environment.update(DATABASE_URL=url.render_as_string(hide_password=False),
                           PYTHONPATH=str(root/'backend/src'),WORKER_AUTO_REFRESH='false',INTELLIGENCE_ENABLED='false')
        info={'side':side,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
              'source_manifest_before':before,'database':url.database,'commands':[]}
        if side == 'repair':
            admin=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT')
            with admin.connect() as connection:
                if connection.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'),{'name':url.database}).first():
                    raise RuntimeError('Repair DB already exists; refusing destructive reset')
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
                metadata['postgres_version']=connection.execute(text('SELECT version()')).scalar_one()
            admin.dispose()
            info['commands'].append(run('repair-migrate',[sys.executable,'-m','alembic','upgrade','head'],root=root,env=environment))
            seed=root/'web/acceptance/rollup-scale/seed.py'
            info['seeder_sha256']=digest(seed)
            info['account_fixture_sha256']=digest(root/'web/acceptance/rollup-scale/account_fixture.py')
            info['scale_fixture_sha256']=digest(root/'backend/tests/integration/rollup_scale_fixture.py')
            info['commands'].append(run('repair-seed',[sys.executable,str(seed),'--rows','2098','--manifest-output',str(OUT/'repair-seed.json')],root=root,env=environment))
        info['harness_sha256']=digest(HARNESS)
        info['commands'].append(run(f'{side}-measure',[sys.executable,str(HARNESS),'--source-root',str(root),'--samples','30','--output',str(OUT/f'{side}.json')],root=root,env=environment))
        info['commands'].append(run(f'{side}-body',[sys.executable,str(OUT/'measure_body.py'),'--source-root',str(root),'--output',str(OUT/f'{side}-body.json')],root=root,env=environment))
        info['source_manifest_after']=source_hash(root)
        info['source_unchanged']=before==info['source_manifest_after']
        info['source_worktree_clean_after']=not bool(source_status(root))
        metadata['runs'].append(info)
        (OUT/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    metadata['finished_at']=now()
    metadata['process_snapshot_after']=subprocess.check_output(['ps','-eo','pid,stat,etime,pcpu,comm'],text=True)
    (OUT/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')


if __name__=='__main__':
    main()
