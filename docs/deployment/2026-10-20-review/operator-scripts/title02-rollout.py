"""Approved GL3-only reversible rollout; preserve runtime, volumes and provider policy."""
import hashlib, json, os, re, shlex, subprocess, sys, tempfile, time
if sys.flags.optimize != 0:
    raise RuntimeError('Rollout requires optimization disabled')
from datetime import UTC, datetime
from pathlib import Path

revision=sys.argv[1]
assert re.fullmatch('[0-9a-f]{40}', revision)
gate=json.loads(Path('/tmp/title02-release-gate.json').read_text())
assert gate['revision']==revision and gate['approved'] is True
tag='title02-'+revision[:12]
root=Path('/etc/gridlens'); active=root/'compose.app.yaml'; runtime_path=root/'runtime.env'
old=active.read_text(); startup=(root/'start-gridlens.py').read_bytes()
assert hashlib.sha256(old.encode()).hexdigest()=='3c0f64f2708df19dda40dc565040314d5dc2972b19690f00a5405d214931d660'
assert hashlib.sha256(startup).hexdigest()=='1cedfc857f6e29e818098f5fbd2e7ae3c691221467864779e350768b1dfd1920'
assert startup.decode().count("'up', '-d', '--no-build'")==1
runtime_sha=hashlib.sha256(runtime_path.read_bytes()).hexdigest()
assert runtime_sha=='b6bd47b38b67501bbc0623a83903748ef100e522d5ddb14d05651117125b9cb9'
assert gate['new_contract_activation'] is False
old_tags={'api':'pr88-85acc0eca4db','web':'title01-d58691eaa5f9'}
runtime={}
for line in runtime_path.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); runtime[k]=shlex.split(v)[0] if v.strip() else ''
for kind in ('api','web'):
    label=subprocess.check_output(['docker','image','inspect','gridlens-'+kind+':'+tag,
        '--format','{{index .Config.Labels "org.opencontainers.image.revision"}}'],text=True).strip()
    assert label==revision,'Image revision mismatch'
    image_id=subprocess.check_output(['docker','image','inspect','gridlens-'+kind+':'+tag,'--format','{{.Id}}'],text=True).strip()
    assert image_id==gate['images'][kind], 'Image digest changed after acceptance'
def verify_old_images():
    expected={'api':'sha256:4cf33d1f20d281b8971ba64dfea87c104dbb644a29a612f60a1e413d5d731609',
              'web':'sha256:51660ba008a571a011d51706699969b91a38bfc897265913fff96bd9dcc78747'}
    for kind,image_id in expected.items():
        actual=subprocess.check_output(['docker','image','inspect','gridlens-'+kind+':'+old_tags[kind],'--format','{{.Id}}'],text=True).strip()
        assert actual==image_id,'Previous image tag changed; rollout must stop'
    return expected
old_images=verify_old_images()
assert old.count('      SAVED_BROWSE_ENABLED: "true"')==2
new=old.replace('gridlens-api:pr88-85acc0eca4db','gridlens-api:'+tag).replace(
    'gridlens-web:title01-d58691eaa5f9','gridlens-web:'+tag)
assert old.count('gridlens-api:pr88-85acc0eca4db') == 1
assert old.count('gridlens-web:title01-d58691eaa5f9') == 1
assert old.count('    <<: *backend') == 4
assert sys.argv[2:] in ([],['--preflight'])
if sys.argv[2:]==['--preflight']:
    print(json.dumps({'preflight_passed':True,'revision':revision,
        'current_compose_sha256':hashlib.sha256(old.encode()).hexdigest(),
        'planned_compose_sha256':hashlib.sha256(new.encode()).hexdigest()}))
    raise SystemExit(0)
stamp=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
backup_compose=root/('compose.app.pre-'+tag+'-'+stamp+'.yaml')
log=Path('/opt/gridlens/releases')/('rollout-'+tag+'-'+stamp+'.log')
for p,data in ((backup_compose,old.encode()),(log,b'')):
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(data)

def run(cmd, *, env=None, input=None, stdin=None, timeout=180):
    with log.open('ab') as out:
        result=subprocess.run(cmd,env=env,input=input,stdin=stdin,stdout=out,stderr=subprocess.STDOUT,timeout=timeout)
    if result.returncode:raise RuntimeError('Private rollout command failed')

def write_compose(content):
    fd,name=tempfile.mkstemp(prefix='compose.app.'+tag+'.',suffix='.staged',dir=root)
    tmp=Path(name)
    try:
        with os.fdopen(fd,'w') as f:f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(tmp,active)
    finally:
        tmp.unlink(missing_ok=True)

def start(services):
    replacement="'--profile', 'saved-browse', 'up', '-d', '--no-build', '--no-deps', "+', '.join(repr(s) for s in services)
    code=startup.decode().replace("'up', '-d', '--no-build'",replacement)
    run(['python3','-'],input=code.encode(),timeout=240)

def query(q, *, isolated=False, database='gridlens_restore_20261014'):
    command=['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=60000',
             'gridlens-map-publication-test-db' if isolated else 'gridlens-db-1','psql']
    command+=['-h','/isolated-pg','-U','postgres'] if isolated else ['-U','gridlens']
    return subprocess.check_output(command+['-d',database,'-X','-At','-c',q],text=True,stderr=subprocess.DEVNULL).strip()

def state(*, isolated=False, database='gridlens_restore_20261014'):
    tables=query("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT LIKE 'browse_%' "
                 "AND tablename NOT IN ('alembic_version','auth_sessions','worker_heartbeats','power_need_titles','power_need_title_versions') ORDER BY tablename",
                 isolated=isolated,database=database).splitlines()
    result={}
    for table in tables:
        assert re.fullmatch(r'[a-z_]+',table)
        result[table]=query("SELECT count(*)::text || ':' || md5(coalesce(string_agg(md5(row_to_json(t)::text),'' "
                           "ORDER BY md5(row_to_json(t)::text)),'')) FROM "+table+' t',isolated=isolated,database=database)
    return result

def controls():
    result={}
    for name in ('api','worker','browse'):
        data=json.loads(subprocess.check_output(['docker','inspect','gridlens-'+name+'-1'],text=True))[0]
        env=dict(x.split('=',1) for x in data['Config']['Env'] if '=' in x)
        result[name]={k:v for k,v in env.items() if k.startswith(('INTELLIGENCE_','BRIEFS_',
            'PURSUITS_','JEV_','MONITORING_','AUTONOMOUS_','POWER_NEED_TITLES_')) or k in ('WORKER_AUTO_REFRESH',
            'DATABASE_URL','APP_PASSWORD_HASH','SESSION_SECRET','OPENAI_API_KEY','TYPESAFE_API_KEY','FIRECRAWL_API_KEY')}
    return result

def ready():
    run(['docker','exec','gridlens-web-1','nginx','-t'])
    run(['docker','exec','gridlens-web-1','nginx','-s','reload'])
    for _ in range(40):
        r=subprocess.run(['docker','exec','gridlens-web-1','wget','-qO-','http://api:8000/health/ready'],capture_output=True,text=True)
        if r.returncode==0 and 'READY' in r.stdout:return
        time.sleep(1)
    raise RuntimeError('Readiness unavailable')

def application_health(expected_images, saved, started_after):
    names=['gridlens-'+name+'-1' for name in ('api','worker','browse','web')]
    for _ in range(40):
        data=json.loads(subprocess.check_output(['docker','inspect',*names],text=True))
        api=next(c for c in data if c['Name']=='/gridlens-api-1')
        heartbeat=query("SELECT coalesce(bool_or(last_seen_at>=to_timestamp("+str(started_after)+") "
                        "AND last_seen_at>now()-interval '30 seconds'),false) FROM worker_heartbeats")=='t'
        result={'containers_running':len(data)==4 and all(c['State']['Running'] for c in data),
                'expected_images':all(c['Image']==expected_images['web' if c['Name']=='/gridlens-web-1' else 'api'] for c in data),
                'worker_heartbeat_fresh':heartbeat,
                'expected_api_mode':('SAVED_BROWSE_ENABLED='+str(saved).lower()) in api['Config']['Env']}
        if all(result.values()):return result
        time.sleep(1)
    raise RuntimeError('Application recovery or worker heartbeat unavailable')

def recover():
    # A failed compose restore must never prevent independent container recovery.
    errors=[]; restored=False; recovery_started=time.time()
    try:
        write_compose(old)
        restored=active.read_text()==old
        if not restored:raise RuntimeError('Compose restore mismatch')
    except Exception as error:errors.append({'phase':'compose_restore','error':type(error).__name__})
    # Keep all policy writers stopped until the previous image has rebuilt.
    # Canonical data is never replaced by a pre-deployment dump.
    for name in ('worker','browse','api'):
        try:run(['docker','stop','--timeout','15','gridlens-'+name+'-1'])
        except Exception as error:errors.append({'phase':'stop_candidate','container':name,'error':type(error).__name__})
    rebuilt=False
    stopped=False
    try:
        states=json.loads(subprocess.check_output(['docker','inspect',*['gridlens-'+name+'-1' for name in ('worker','browse','api')]],text=True))
        stopped=len(states)==3 and all(not item['State']['Running'] for item in states)
        assert stopped,'Policy writers are still running'
        assert verify_old_images()==old_images
    except Exception as error:errors.append({'phase':'rollback_preflight','error':type(error).__name__})
    if restored and stopped and not any(e['phase'] in ('stop_candidate','rollback_preflight') for e in errors):
        try:
            old_builder=[(old_images['api'] if x==gate['images']['api'] else x) for x in builder]
            run(old_builder+['uv','run','python','-m','gridlens.jobs.browse','rebuild'],env=env,timeout=300)
            rebuilt=True
        except Exception as error:errors.append({'phase':'old_policy_rebuild','error':type(error).__name__})
        if rebuilt:
            try:
                assert verify_old_images()==old_images
                start(['api','worker','browse','web'])
            except Exception as error:errors.append({'phase':'compose_start','error':type(error).__name__})
    # Retry only containers proven to be from the previous image version.
    if rebuilt:
        for name in ('api','web','worker','browse'):
            try:
                current=subprocess.check_output(['docker','inspect','gridlens-'+name+'-1','--format','{{.Image}}'],text=True).strip()
                expected='sha256:51660ba008a571a011d51706699969b91a38bfc897265913fff96bd9dcc78747' if name=='web' else 'sha256:4cf33d1f20d281b8971ba64dfea87c104dbb644a29a612f60a1e413d5d731609'
                assert current==expected,'Cannot restart a mixed-policy candidate during rollback'
                run(['docker','start','gridlens-'+name+'-1'])
            except Exception as error:errors.append({'phase':'container_start','container':name,'error':type(error).__name__})
    health=None
    try:
        ready()
        health=application_health(old_images,True,recovery_started)
        assert controls()==prior_controls,'Approved controls changed during recovery'
        status=json.loads(subprocess.check_output(['docker','exec','gridlens-api-1','uv','run','python','-m','gridlens.jobs.browse','status'],text=True))
        assert status['status']=='current', 'Previous policy is not current after rollback'
    except Exception as error:errors.append({'phase':'recovery_validation','error':type(error).__name__})
    return {'fallback_ready':restored and rebuilt and health is not None and not any(e['phase']=='recovery_validation' for e in errors),
            'recovery_errors':errors,'recovery_health':health}

assert query("SELECT count(*) FROM jobs WHERE status='running'")=='0','Worker must be idle'
prior_controls=controls()
assert prior_controls['worker']['JEV_ENABLED']=='false'
assert all(values.get('POWER_NEED_TITLES_ENABLED','false').lower()=='false' for values in prior_controls.values())
assert query("SELECT count(*) FROM logical_calls WHERE status IN ('NOT_SENT','SENT_OUTCOME_UNKNOWN')")=='0'
assert query('SELECT version_num FROM alembic_version')=='0031_research_browse'
assert all('POWER_NEED_TITLE' not in values.get('INTELLIGENCE_ENABLED_CONTRACTS','') and 'SIGNAL_ADJUDICATION' not in values.get('INTELLIGENCE_ENABLED_CONTRACTS','') for values in prior_controls.values())
pg_test='gridlens-map-publication-test-db'
pg_state=json.loads(subprocess.check_output(['docker','inspect',pg_test],text=True))[0]
assert not pg_state['State']['Running'] and pg_state['HostConfig']['NetworkMode']=='none'
assert any(m['Source']=='/opt/gridlens/performance/map-publication-20261019/pgdata' and m['Destination']=='/var/lib/postgresql' for m in pg_state['Mounts'])
overrides={'DATABASE_URL':runtime['COMPOSE_DATABASE_URL'],
     'APP_PASSWORD_HASH':'non-authenticating-migration-only','SESSION_SECRET':'migration-no-http-service',
     'OPENAI_API_KEY':'','TYPESAFE_API_KEY':'','FIRECRAWL_API_KEY':'','WORKER_AUTO_REFRESH':'false',
     'INTELLIGENCE_ENABLED':'false','INTELLIGENCE_OPENAI_ENABLED':'false','INTELLIGENCE_TYPESAFE_ENABLED':'false',
     'INTELLIGENCE_RESEARCH_ENABLED':'false','AUTONOMOUS_RESEARCH_ENABLED':'false','JEV_ENABLED':'false',
     'INTELLIGENCE_ENABLED_CONTRACTS':'','POWER_NEED_TITLES_ENABLED':'false',
     'JEV_SHADOW_MODE':'false','MONITORING_ENABLED':'false','SAVED_BROWSE_ENABLED':'true'}
env={**os.environ,**overrides}
builder=['docker','run','--rm','--network','gridlens_default']
for key in overrides:builder+=['-e',key]
builder+=[gate['images']['api']]
report={'revision':revision,'tag':tag,'private_log':str(log),'prior_compose':str(backup_compose)}

def stop_idle_worker():
    # SHARE blocks a new lease UPDATE from committing between the idle check and
    # shutdown. A worker blocked before lease commit cannot start external I/O.
    with log.open('ab') as errors:
        fence=subprocess.Popen(['docker','exec','-i','gridlens-db-1','psql','-U','gridlens',
            '-d','gridlens_restore_20261014','-X','-A','-t','-q','-v','ON_ERROR_STOP=1'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True)
        try:
            fence.stdin.write("BEGIN; SET LOCAL lock_timeout='1000ms'; LOCK TABLE jobs IN SHARE MODE; "
                "SELECT 'DRAIN_READY:' || count(*) FROM jobs WHERE status='running';\n")
            fence.stdin.flush()
            assert fence.stdout.readline().strip()=='DRAIN_READY:0','Idle drain unavailable'
            run(['docker','stop','--timeout','15','gridlens-worker-1'])
        finally:
            if fence.poll() is None:
                fence.communicate('ROLLBACK;\n\\q\n',timeout=10)

test_started=False
try:
    run(['docker','start',pg_test]);test_started=True
    for _ in range(30):
        if subprocess.run(['docker','exec',pg_test,'pg_isready','-h','/isolated-pg','-U','postgres'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
        time.sleep(1)
    else:raise RuntimeError('Isolated restore database unavailable')
    stop_idle_worker()
    run(['docker','stop','--timeout','15','gridlens-browse-1'])
    assert query("SELECT count(*) FROM jobs WHERE status='running'")=='0'
    run(['docker','stop','--timeout','15','gridlens-api-1'])
    before=state()
    dump=Path('/opt/gridlens/backups')/('pre-'+tag+'-'+stamp+'.dump')
    fd=os.open(dump,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as out:
        result=subprocess.run(['docker','exec','gridlens-db-1','pg_dump','-U','gridlens',
            '-d','gridlens_restore_20261014','-Fc','--no-owner','--no-acl'],stdout=out,stderr=subprocess.PIPE,timeout=180)
        assert result.returncode==0,'Backup failed'
        out.flush();os.fsync(out.fileno())
    with dump.open('rb') as f:run(['docker','exec','-i','gridlens-db-1','pg_restore','-l'],stdin=f)
    restored='gridlens_title02_release_'+revision[:12]
    run(['docker','exec','gridlens-map-publication-test-db','createdb','-h','/isolated-pg','-U','postgres',restored])
    with dump.open('rb') as f:
        run(['docker','exec','-i','gridlens-map-publication-test-db','pg_restore','-h','/isolated-pg',
            '-U','postgres','-d',restored,'--no-owner','--no-acl','--exit-on-error'],stdin=f,timeout=300)
    assert state(isolated=True,database=restored)==before,'Isolated restored state mismatch'
    with dump.open('rb') as f:backup_hash=hashlib.file_digest(f,'sha256').hexdigest()
    report['backup']={'path':str(dump),'bytes':dump.stat().st_size,
                      'sha256':backup_hash,'restore_verified':True}
    print(json.dumps({'phase':'backup_restore','backup':report['backup']}),flush=True)
    for args in (['upgrade','head'],['upgrade','head'],['check']):
        run(builder+['uv','run','alembic']+args,env=env)
    assert state()==before,'Migration changed canonical state'
    assert query('SELECT version_num FROM alembic_version')=='0032_power_need_titles'
    assert query('SELECT (SELECT count(*) FROM power_need_titles)+(SELECT count(*) FROM power_need_title_versions)')=='0'
    run(builder+['uv','run','python','-m','gridlens.jobs.browse','rebuild'],env=env,timeout=240)
    assert state()==before,'Rebuild changed canonical state'
    print(json.dumps({'phase':'migration_and_rebuild','canonical_state_unchanged':True,
                      'schema':query('SELECT version_num FROM alembic_version')}),flush=True)
    write_compose(new)
    started_after=time.time()
    start(['api','worker','browse','web']);ready()
    report['application_health']=application_health(gate['images'],True,started_after)
    assert controls()==prior_controls,'Approved controls or credentials changed'
    assert hashlib.sha256(runtime_path.read_bytes()).hexdigest()==runtime_sha,'Private runtime changed'
    status=json.loads(subprocess.check_output(['docker','exec','gridlens-api-1','uv','run','python',
        '-m','gridlens.jobs.browse','status'],text=True))
    assert status['status']=='current'
    report.update(passed=True,status=status,canonical_state_unchanged=True,approved_policy_unchanged=True)
except Exception as error:
    report.update(passed=False,error_type=type(error).__name__,schema_retained=True)
    report.update(recover())
    print(json.dumps(report),flush=True)
    raise SystemExit(1)
finally:
    report['test_database_stopped']=False
    try:
        if test_started:run(['docker','stop','--timeout','15',pg_test])
        stopped_state=json.loads(subprocess.check_output(['docker','inspect',pg_test],text=True))[0]
        report['test_database_stopped']=not stopped_state['State']['Running']
        assert report['test_database_stopped']
    except Exception as cleanup_error:
        report['cleanup_error_type']=type(cleanup_error).__name__
        report['passed']=False
    receipt=Path('/opt/gridlens/releases')/('title02-rollout-'+revision[:12]+'.json')
    receipt.write_text(json.dumps(report,indent=2));os.chmod(receipt,0o600)
print(json.dumps(report),flush=True)
raise SystemExit(0 if report['passed'] else 1)
