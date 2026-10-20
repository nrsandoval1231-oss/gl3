"""Show only configuration wiring and resource usage, never private values."""
import json
import re
import shutil
import subprocess
from pathlib import Path

compose = Path('/etc/gridlens/compose.app.yaml').read_text()
print(json.dumps({
    'env_file_lines': [line.strip() for line in compose.splitlines() if 'env_file' in line],
    'referenced_variable_names': sorted(set(re.findall(r'\$\{([A-Z][A-Z0-9_]*)', compose))),
    'explicit_setting_names': sorted(set(re.findall(r'^\s+([A-Z][A-Z0-9_]+):', compose, re.M))),
    'activation_related_lines': [line.strip() for line in compose.splitlines()
        if re.match(r'^\s+(JEV_ENABLED|INTELLIGENCE_ENABLED|WORKER_AUTO_REFRESH|SAVED_BROWSE_ENABLED):', line)],
    'disk_free_bytes': shutil.disk_usage('/opt/gridlens').free,
    'memory_total_kib': int(re.search(r'MemTotal:\s+(\d+)', Path('/proc/meminfo').read_text()).group(1)),
    'memory_available_kib': int(re.search(r'MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text()).group(1)),
    'cpus': subprocess.check_output(['nproc'], text=True).strip(),
}))
