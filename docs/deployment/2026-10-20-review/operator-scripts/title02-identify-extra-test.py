import json
import subprocess

command = ['docker', 'run', '--rm', '--network', 'none', '--cpus', '1', '--memory', '1g',
 '-v', '/opt/gridlens/releases/title02-test-8f5d19165ab5:/workspace:ro', '-w', '/workspace/backend',
 '-e', 'PYTHONPATH=/workspace/backend/src', '-e', 'PYTHONDONTWRITEBYTECODE=1',
 '-e', 'DATABASE_URL=postgresql+psycopg://postgres@/synthetic',
 '-e', 'TEST_DATABASE_URL=postgresql+psycopg://postgres@/synthetic',
 '-e', 'APP_PASSWORD_HASH=non-authenticating-collection', '-e', 'SESSION_SECRET=synthetic-collection',
 'sha256:fd9f8d786b37a2a8e6afcfd0526443fb43310e2875623b8431efa8cda7bae628',
 '/app/backend/.venv/bin/pytest', '--collect-only', '-q', '-o', 'cache_dir=/tmp/collection']
out = subprocess.run(command, capture_output=True, text=True, timeout=90)
assert out.returncode == 0, out.stdout[-2500:]
nodes = [line.strip() for line in out.stdout.splitlines() if line.startswith('tests/') and '::' in line]
print(json.dumps({'count': len(nodes), 'range': [{'ordinal': i+1, 'node': nodes[i]} for i in range(1400, 1450)]}))
