"""Restart only the same idle GL3 containers; preserve unknown accounting exactly."""
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

names=['gridlens-'+s+'-1' for s in ('api','worker','browse','web','db')]
original={c['Name'].lstrip('/'):c for c in json.loads(subprocess.check_output(['docker','inspect',*names],text=True))}
assert all(c['State']['Running'] for c in original.values())
for service in ('api','worker','browse'):
    c=original['gridlens-'+service+'-1']
    assert c['Image']=='sha256:be07ead1cecc353e500a1f657ae3d4c8ab6062820c4f121f2558adc6f23ded07'
    env=dict(x.split('=',1) for x in c['Config']['Env'] if '=' in x)
    assert env.get('POWER_NEED_TITLES_ENABLED','false')=='false'
    assert env['JEV_ENABLED']=='false'
assert original['gridlens-web-1']['Image']=='sha256:f816a62a84e412bfc475ac8a773c34032a599baa04dd07b23893776dc1c8f5f2'
assert any(m.get('Name')=='gridlens_postgres-data' and m['Destination']=='/var/lib/postgresql' for m in original['gridlens-db-1']['Mounts'])
controller=subprocess.run(['docker','ps','-a','--format','{{.Names}}'],capture_output=True,text=True,check=True)
assert 'gridlens-title02-six-intents' not in controller.stdout.splitlines()
def query(sql):
    return subprocess.check_output(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on',
        'gridlens-db-1','psql','-U','gridlens','-d','gridlens_restore_20261014','-X','-At','-c',sql],text=True,stderr=subprocess.DEVNULL).strip()
journal=Path('/opt/gridlens/releases/title02-802cbb4055c5/validation-control/title02-six-intents.jsonl')
intents=json.loads(journal.read_text().splitlines()[0])['intents']
assert len(intents)==6
assert [i['kind'] for i in intents].count('power_need_title')==3
assert [i['kind'] for i in intents].count('signal_adjudication')==3
ids=[i['job_id'] for i in intents]
from uuid import UUID
ids=[str(UUID(i)) for i in ids]
assert len(set(ids))==6
def state():
    result={}
    for table in ('logical_calls','logical_call_budgets','power_need_titles','power_need_title_versions','jobs'):
        where=" WHERE id IN ("+','.join("'"+i+"'" for i in ids)+')' if table=='jobs' else ''
        result[table]=query("SELECT count(*)::text||':'||md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) FROM (SELECT * FROM "+table+where+")t")
    return result
def run(command):
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def configuration_hashes():
    return {name:hashlib.sha256((Path('/etc/gridlens')/name).read_bytes()).hexdigest()
        for name in ('runtime.env','compose.app.yaml','start-gridlens.py')}
config_before=configuration_hashes()
report={'started_at':datetime.now(UTC).isoformat(),'passed':False,'provider_requests_by_controller':0}
before=state()
assert query("SELECT count(*) FROM jobs WHERE status='running'")=='0'
assert query("SELECT count(*) FROM logical_calls WHERE status='SENT_OUTCOME_UNKNOWN'")=='1'
assert query("SELECT status||':'||max_cost_usd::text FROM logical_calls WHERE id='4d688637-3715-4efa-bce8-19fd41e51e09'")=='SENT_OUTCOME_UNKNOWN:0.000434'
job_rows=json.loads(query("SELECT json_agg(x) FROM (SELECT id,kind,status,attempts,error FROM jobs WHERE id IN ("+','.join("'"+i+"'" for i in ids)+"))x"))
assert len(job_rows)==6
by_id={r['id']:r for r in job_rows}
for index,intent in enumerate(intents):
    row=by_id[intent['job_id']]
    assert row['kind']==intent['kind']
    assert row['status']==('succeeded' if index<4 else 'failed')
    assert row['attempts']==(0 if index==5 else 1)
    assert row['error']==(None if index<4 else 'ProviderResponseError' if index==4 else 'release_validation_held_for_review')
errors=[]
try:
    try:
        run(['docker','stop','--timeout','15','gridlens-api-1','gridlens-browse-1'])
        fence=subprocess.Popen(['docker','exec','-i','gridlens-db-1','psql','-U','gridlens','-d','gridlens_restore_20261014',
            '-X','-A','-t','-q','-v','ON_ERROR_STOP=1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        try:
            fence.stdin.write("BEGIN; SET LOCAL lock_timeout='1000ms'; LOCK TABLE jobs IN SHARE MODE; SELECT 'IDLE:'||count(*) FROM jobs WHERE status='running';\n")
            fence.stdin.flush()
            assert fence.stdout.readline().strip()=='IDLE:0'
            run(['docker','stop','--timeout','15','gridlens-worker-1'])
        finally:
            if fence.poll() is None:fence.communicate('ROLLBACK;\n\\q\n',timeout=10)
    finally:
        for service in ('api','browse','worker'):
            name='gridlens-'+service+'-1'
            try:
                current=json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
                assert current['Id']==original[name]['Id'] and current['Image']==original[name]['Image']
                assert current['Config']['Env']==original[name]['Config']['Env']
                run(['docker','start',name])
            except Exception as recovery_error:
                errors.append({'phase':'container_recovery','container':name,'error_type':type(recovery_error).__name__})
    assert not errors, 'One or more same-container recovery operations failed'
    started_after=time.time()
    run(['docker','exec','gridlens-web-1','nginx','-t'])
    run(['docker','exec','gridlens-web-1','nginx','-s','reload'])
    for _ in range(45):
        r=subprocess.run(['docker','exec','gridlens-web-1','wget','-qO-','http://api:8000/health/ready'],capture_output=True,text=True)
        heartbeat=query("SELECT coalesce(bool_or(last_seen_at>=to_timestamp("+str(started_after)+") AND last_seen_at>now()-interval '30 seconds'),false) FROM worker_heartbeats")=='t'
        if r.returncode==0 and 'READY' in r.stdout and heartbeat:break
        time.sleep(1)
    else:raise RuntimeError('Restart health unavailable')
    assert state()==before, 'Retained results, checkpoints or accounting changed'
    current={c['Name'].lstrip('/'):c for c in json.loads(subprocess.check_output(['docker','inspect',*names],text=True))}
    assert all(c['State']['Running'] for c in current.values())
    assert all(current[n]['Id']==original[n]['Id'] and current[n]['Config']['Env']==original[n]['Config']['Env'] for n in names)
    assert configuration_hashes()==config_before
    report.update(passed=True,same_containers_and_environment=True,configuration_sha256=config_before,
        preserved_state=before,unknown_call_preserved=True,application_ready=True,fresh_worker_heartbeat=True)
except BaseException as error:
    errors.append({'phase':'restart_validation','error_type':type(error).__name__})
finally:
    report.update(finished_at=datetime.now(UTC).isoformat(),errors=errors)
    Path('/opt/gridlens/releases/title02-restart-preservation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
