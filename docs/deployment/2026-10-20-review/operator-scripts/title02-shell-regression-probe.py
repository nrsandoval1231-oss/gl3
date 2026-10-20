"""Compare supplemental Windows bytes with exact Git export, no network/DB."""
import json
import subprocess
from pathlib import Path

roots = ['/opt/gridlens/releases/title02-test-8f5d19165ab5', '/opt/gridlens/releases/title02-802cbb4055c5']
results = []
for source in roots:
    script = (Path(source) / 'deploy/digitalocean/with-infisical.sh').read_bytes()
    command = ['docker', 'run', '--rm', '--network', 'none', '--cpus', '1', '--memory', '1g',
        '-v', source + ':/workspace:ro', '-w', '/workspace/backend',
        '-e', 'PYTHONPATH=/workspace/backend/src', '-e', 'PYTHONDONTWRITEBYTECODE=1',
        '-e', 'DATABASE_URL=postgresql+psycopg://postgres@/synthetic',
        '-e', 'TEST_DATABASE_URL=postgresql+psycopg://postgres@/synthetic',
        '-e', 'APP_PASSWORD_HASH=non-authenticating-test', '-e', 'SESSION_SECRET=synthetic-test',
        'sha256:fd9f8d786b37a2a8e6afcfd0526443fb43310e2875623b8431efa8cda7bae628',
        '/app/backend/.venv/bin/pytest', '-q', '--tb=short', '-o', 'cache_dir=/tmp/test',
        'tests/unit/test_jev_runtime.py::test_infisical_wrapper_uses_explicit_existing_binding']
    out = subprocess.run(command, capture_output=True, text=True, timeout=120)
    item = {'source': source, 'crlf_lines': script.count(b'\r\n'), 'exit_code': out.returncode,
            'output': (out.stdout + out.stderr)[-5000:]}
    results.append(item)
    print(json.dumps(item), flush=True)
assert [r['exit_code'] for r in results] == [1, 0]
print(json.dumps({'diagnosis': 'Supplemental Windows archive omitted executable mode; exact Git export preserves it and unchanged test passes',
                  'passed': True, 'network': 'none', 'database_access': False, 'production_mutation': False}))
