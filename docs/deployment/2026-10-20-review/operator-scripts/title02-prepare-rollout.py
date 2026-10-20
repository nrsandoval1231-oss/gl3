"""Adapt the verified PR88 drain/backup/recovery controller to today's baseline."""
from pathlib import Path

root = Path(__file__).resolve().parent
code = (root / "pr88-rollout.py").read_text()

def replace(old, new, count=1):
    global code
    assert code.count(old) == count, old
    code = code.replace(old, new)

replace("import hashlib, json, os, re, shlex, subprocess, sys, tempfile, time", "import hashlib, json, os, re, shlex, subprocess, sys, tempfile, time\nif sys.flags.optimize != 0:\n    raise RuntimeError('Rollout requires optimization disabled')")
replace("'/tmp/pr88-release-gate.json'", "'/tmp/title02-release-gate.json'")
replace("tag='pr88-'+revision[:12]", "tag='title02-'+revision[:12]")
replace("349f88fd17484f6471d2660cfdaf7f97a1fec522a9cc8d1b45b6c0b23f1612da", "3c0f64f2708df19dda40dc565040314d5dc2972b19690f00a5405d214931d660")
replace("runtime_sha=hashlib.sha256(runtime_path.read_bytes()).hexdigest()", "runtime_sha=hashlib.sha256(runtime_path.read_bytes()).hexdigest()\nassert runtime_sha=='b6bd47b38b67501bbc0623a83903748ef100e522d5ddb14d05651117125b9cb9'\nassert gate['new_contract_activation'] is False\nold_tags={'api':'pr88-85acc0eca4db','web':'title01-d58691eaa5f9'}")
replace("sha256:6630d7004b280ce342fe0643e045bf836fbfbe1af08bf46f33924879b9d4d032", "sha256:4cf33d1f20d281b8971ba64dfea87c104dbb644a29a612f60a1e413d5d731609", 2)
replace("sha256:abf17ba3606a4e97a4ba94a4c36dd309419fe9ccc7127c09b7e9c9d677f76d21", "sha256:51660ba008a571a011d51706699969b91a38bfc897265913fff96bd9dcc78747", 2)
replace("'gridlens-'+kind+':map-48e18c29285b'", "'gridlens-'+kind+':'+old_tags[kind]")
replace("gridlens-api:map-48e18c29285b", "gridlens-api:pr88-85acc0eca4db", 2)
replace("gridlens-web:map-48e18c29285b", "gridlens-web:title01-d58691eaa5f9", 2)
replace("AND tablename NOT IN ('alembic_version','auth_sessions','worker_heartbeats') ORDER BY tablename", "AND tablename NOT IN ('alembic_version','auth_sessions','worker_heartbeats','power_need_titles','power_need_title_versions') ORDER BY tablename")
replace("def application_health(expected_tag, saved, started_after):", "def application_health(expected_images, saved, started_after):")
replace("all(c['Config']['Image']=='gridlens-'+('web' if c['Name']=='/gridlens-web-1' else 'api')+':'+expected_tag for c in data)", "all(c['Image']==expected_images['web' if c['Name']=='/gridlens-web-1' else 'api'] for c in data)")
replace("application_health('map-48e18c29285b',True,recovery_started)", "application_health(old_images,True,recovery_started)")
replace("application_health(tag,True,started_after)", "application_health(gate['images'],True,started_after)")
replace("'PURSUITS_','JEV_','MONITORING_','AUTONOMOUS_')", "'PURSUITS_','JEV_','MONITORING_','AUTONOMOUS_','POWER_NEED_TITLES_')")
replace("WHERE status='running' AND lease_until>now()", "WHERE status='running'", 3)
replace("assert prior_controls['worker']['JEV_ENABLED']=='false'", "assert prior_controls['worker']['JEV_ENABLED']=='false'\nassert all(values.get('POWER_NEED_TITLES_ENABLED','false').lower()=='false' for values in prior_controls.values())\nassert query(\"SELECT count(*) FROM logical_calls WHERE status IN ('NOT_SENT','SENT_OUTCOME_UNKNOWN')\")=='0'\nassert query('SELECT version_num FROM alembic_version')=='0031_research_browse'\nassert all('POWER_NEED_TITLE' not in values.get('INTELLIGENCE_ENABLED_CONTRACTS','') and 'SIGNAL_ADJUDICATION' not in values.get('INTELLIGENCE_ENABLED_CONTRACTS','') for values in prior_controls.values())\npg_test='gridlens-map-publication-test-db'\npg_state=json.loads(subprocess.check_output(['docker','inspect',pg_test],text=True))[0]\nassert not pg_state['State']['Running'] and pg_state['HostConfig']['NetworkMode']=='none'\nassert any(m['Source']=='/opt/gridlens/performance/map-publication-20261019/pgdata' and m['Destination']=='/var/lib/postgresql' for m in pg_state['Mounts'])")
replace("'INTELLIGENCE_RESEARCH_ENABLED':'false','AUTONOMOUS_RESEARCH_ENABLED':'false','JEV_ENABLED':'false',", "'INTELLIGENCE_RESEARCH_ENABLED':'false','AUTONOMOUS_RESEARCH_ENABLED':'false','JEV_ENABLED':'false',\n     'INTELLIGENCE_ENABLED_CONTRACTS':'','POWER_NEED_TITLES_ENABLED':'false',")
replace("try:\n    stop_idle_worker()", "test_started=False\ntry:\n    run(['docker','start',pg_test]);test_started=True\n    for _ in range(30):\n        if subprocess.run(['docker','exec',pg_test,'pg_isready','-h','/isolated-pg','-U','postgres'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break\n        time.sleep(1)\n    else:raise RuntimeError('Isolated restore database unavailable')\n    stop_idle_worker()")
replace("restored='gridlens_pr88_release_'+revision[:12]", "restored='gridlens_title02_release_'+revision[:12]")
replace("assert state()==before,'Migration changed canonical state'", "assert state()==before,'Migration changed canonical state'\n    assert query('SELECT version_num FROM alembic_version')=='0032_power_need_titles'\n    assert query('SELECT (SELECT count(*) FROM power_need_titles)+(SELECT count(*) FROM power_need_title_versions)')=='0'")
replace("    raise SystemExit(1)\nprint(json.dumps(report),flush=True)", "    raise SystemExit(1)\nfinally:\n    report['test_database_stopped']=False\n    try:\n        if test_started:run(['docker','stop','--timeout','15',pg_test])\n        stopped_state=json.loads(subprocess.check_output(['docker','inspect',pg_test],text=True))[0]\n        report['test_database_stopped']=not stopped_state['State']['Running']\n        assert report['test_database_stopped']\n    except Exception as cleanup_error:\n        report['cleanup_error_type']=type(cleanup_error).__name__\n        report['passed']=False\n    receipt=Path('/opt/gridlens/releases')/('title02-rollout-'+revision[:12]+'.json')\n    receipt.write_text(json.dumps(report,indent=2));os.chmod(receipt,0o600)\nprint(json.dumps(report),flush=True)\nraise SystemExit(0 if report['passed'] else 1)")
assert "map-48e18c29285b" not in code
compile(code, "title02-rollout.py", "exec")
(root / "title02-rollout.py").write_text(code, encoding="utf-8")
print("Prepared TITLE-02 rollout; no remote action performed")
