"""Read retained validation status; redact existing private values from errors."""
import json
import re
import subprocess
from pathlib import Path
root = Path('/opt/gridlens/releases/title02-802cbb4055c5/validation-control')
env = json.loads(subprocess.check_output(['docker','inspect','gridlens-api-1'],text=True))[0]['Config']['Env']
secrets = [entry.split('=',1)[1] for entry in env if '=' in entry and any(token in entry.split('=',1)[0] for token in ('KEY','SECRET','PASSWORD','DATABASE_URL'))]
log = (root/'host-private.log').read_text()
for value in secrets:
    if value: log = log.replace(value, '[REDACTED]')
safe_lines = [line for line in log.splitlines() if re.search(r'Traceback|File "/|AssertionError|RuntimeError|KeyError|ValueError|TypeError|Error:',line)]
journal_path = root/'title02-six-intents.jsonl'
journal = [json.loads(line) for line in journal_path.read_text().splitlines()] if journal_path.exists() else []
sql = "SELECT json_build_object('calls',(SELECT json_agg(x) FROM (SELECT id,task_type,status,blocked_reason,provider,model,job_id,max_cost_usd,actual_cost_usd,input_tokens,output_tokens FROM logical_calls ORDER BY created_at DESC LIMIT 10)x),'jobs',(SELECT json_agg(x) FROM (SELECT id,kind,target_id,status,error,attempts,checkpoint FROM jobs WHERE kind IN ('power_need_title','signal_adjudication') ORDER BY created_at DESC LIMIT 10)x));"
out = subprocess.check_output(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on','gridlens-db-1','psql','-U','gridlens','-d','gridlens_restore_20261014','-X','-At','-c',sql],text=True,stderr=subprocess.DEVNULL)
print(json.dumps({'error_trace':safe_lines[-20:],'journal':journal,'database':json.loads(out)}))
