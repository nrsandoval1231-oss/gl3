"""Exercise ambiguous Docker state admission without importing the host script."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

source = Path(__file__).with_name('title02-six-intent-host.py').read_text()
module = ast.parse(source)
function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'controller_state')
code = compile(ast.Module(body=[function], type_ignores=[]), 'reviewed-controller-state', 'exec')
cases = [
    ('running', [(0, 'true\n')], 'running'),
    ('stopped', [(0, 'false\n')], 'stopped'),
    ('confirmed_absent', [(1, ''), (0, 'gridlens-api-1\n')], 'absent'),
    ('inspect_failed_but_present', [(1, ''), (0, 'gridlens-title02-six-intents\n')], 'unknown'),
    ('daemon_unavailable', [(1, ''), (1, '')], 'unknown'),
    ('malformed_inspect_present', [(0, 'invalid'), (0, 'gridlens-title02-six-intents\n')], 'unknown'),
]
results = []
for name, responses, expected in cases:
    pending = list(responses)
    def run(*args, **kwargs):
        returncode, stdout = pending.pop(0)
        return SimpleNamespace(returncode=returncode, stdout=stdout)
    namespace = {'subprocess': SimpleNamespace(run=run)}
    exec(code, namespace)
    assert namespace['controller_state']() == expected and not pending
    results.append({'case': name, 'state': expected, 'passed': True})
receipt = {'cases': results, 'docker_actions': 0, 'provider_calls': 0, 'database_access': False}
Path(__file__).with_name('title02-controller-host-offline.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
