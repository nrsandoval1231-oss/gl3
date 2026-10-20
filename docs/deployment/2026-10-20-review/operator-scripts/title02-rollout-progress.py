import json
import subprocess
from pathlib import Path
names = ['gridlens-' + value + '-1' for value in ('api', 'worker', 'browse', 'web', 'db')]
items = json.loads(subprocess.check_output(['docker', 'inspect', *names], text=True))
log = max(Path('/opt/gridlens/releases').glob('rollout-title02-802cbb4055c5-*.log'), key=lambda p: p.stat().st_mtime)
query = "SELECT json_build_object('schema',(SELECT version_num FROM alembic_version),'running_jobs',(SELECT count(*) FROM jobs WHERE status='running'),'logical_calls',(SELECT count(*) FROM logical_calls));"
state = json.loads(subprocess.check_output(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on','gridlens-db-1','psql','-U','gridlens','-d','gridlens_restore_20261014','-X','-At','-c',query],text=True))
print(json.dumps({'containers': [{'name': x['Name'], 'running': x['State']['Running'], 'image': x['Image']} for x in items],
 'private_log_bytes': log.stat().st_size, 'database': state}))
