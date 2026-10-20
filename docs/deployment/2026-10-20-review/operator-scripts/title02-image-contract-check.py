"""Read-only packaged API and web checks, with no network or real keys."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

revision = sys.argv[1]
assert re.fullmatch('[0-9a-f]{40}', revision)
release = Path('/opt/gridlens/releases') / ('title02-' + revision[:12])
build = json.loads((release / 'build-evidence.json').read_text())
assert build['revision'] == revision
images = {kind: build['images']['gridlens-' + kind + ':title02-' + revision[:12]] for kind in ('api', 'web')}
for image in images.values():
    label = subprocess.check_output(['docker', 'image', 'inspect', image, '--format',
        '{{index .Config.Labels "org.opencontainers.image.revision"}}'], text=True).strip()
    assert label == revision
source = '''import json
from gridlens.api.app import app
from gridlens.settings import settings
assert not settings.power_need_titles_enabled
assert not settings.intelligence_typesafe_enabled
assert not settings.jev_enabled
print(json.dumps(app.openapi()))
'''
command = ['docker', 'run', '--rm', '-i', '--network', 'none', '--cpus', '1', '--memory', '1g',
    '-e', 'DATABASE_URL=postgresql+psycopg://unavailable:unavailable@127.0.0.1/unavailable',
    '-e', 'APP_PASSWORD_HASH=non-authenticating-image-contract-only',
    '-e', 'SESSION_SECRET=contract-only-no-http', '-e', 'OPENAI_API_KEY=', '-e', 'TYPESAFE_API_KEY=',
    '-e', 'FIRECRAWL_API_KEY=', images['api'], 'uv', 'run', 'python', '-']
schema = json.loads(subprocess.check_output(command, input=source, text=True))
export = json.loads((release / 'web/src/api/openapi.json').read_text())
assert schema == export
index = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat',
                                 images['web'], '/usr/share/nginx/html/index.html'], text=True)
assets = re.findall(r'(?:src|href)="(/assets/[^" ]+)"', index)
assert any(path.endswith('.js') for path in assets) and any(path.endswith('.css') for path in assets)
for path in assets:
    subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'test',
                    images['web'], '-f', '/usr/share/nginx/html' + path], check=True)
receipt = {'revision': revision, 'images': images, 'packaged_openapi_parity': True,
           'new_contracts_default_disabled': True, 'web_assets_present': assets,
           'index_sha256': hashlib.sha256(index.encode()).hexdigest(), 'network': 'none',
           'provider_calls': 0, 'database_queries': 0, 'running_services_changed': False}
(release / 'packaged-contract-evidence.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
