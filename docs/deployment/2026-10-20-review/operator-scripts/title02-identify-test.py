"""Read test collection to identify the first failure while the full run finishes."""
import json
import subprocess

result = subprocess.run(['docker', 'exec', 'gridlens-title02-backend-tests',
    '/app/backend/.venv/bin/pytest', '--collect-only', '-q', '-o', 'cache_dir=/tmp/title02-collection'],
    capture_output=True, text=True, timeout=90)
assert result.returncode == 0, 'Test collection unavailable'
nodes = [line.strip() for line in result.stdout.splitlines() if line.startswith('tests/') and '::' in line]
print(json.dumps({'count': len(nodes), 'range': [{'ordinal': index + 1, 'node': nodes[index]}
    for index in range(309, 320)]}))
