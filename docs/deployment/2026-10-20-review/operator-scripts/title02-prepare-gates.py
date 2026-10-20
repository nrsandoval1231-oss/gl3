"""Bind actual user approval and completed release evidence to guarded actions."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).parent
def read(name):
    return json.loads((root / name).read_text(encoding='utf-8-sig'))
def sha(name):
    return hashlib.sha256((root / name).read_bytes()).hexdigest()
def write(name, value):
    (root / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

authorization = read('title02-authorization-20261020.json')
revision = authorization['revision']
ci = read('title02-pr90-ci.json')
merged = read('title02-pr90-merged.json')
assert merged['state'] == 'MERGED' and merged['headRefOid'] == revision
assert ci['headRefOid'] == revision and len(ci['statusCheckRollup']) == 4
assert all(item['conclusion'] == 'SUCCESS' for item in ci['statusCheckRollup'])
assert authorization['approved'] and authorization['initial_six_public_intents_authorized']
images = {'api': 'sha256:be07ead1cecc353e500a1f657ae3d4c8ab6062820c4f121f2558adc6f23ded07',
          'web': 'sha256:f816a62a84e412bfc475ac8a773c34032a599baa04dd07b23893776dc1c8f5f2'}
evidence = ('Nick answered Approved at 2026-10-20 00:51 UTC to the 00:28 public-data scope question; '
    'user message Sentinel_7bc863947fa0819185e1890c8b48f91b, question Sentinel_5b1040292d908191824361f7fa8b4de2, '
    'relayed by parent 01a143b7-e94c-738f-9bd8-06f1aed59018. Covers six fixed public validation jobs, '
    'then explicit public title requests and Jev updates within the reviewed three-observation scope; '
    'shared $50 monthly and all narrower limits unchanged. No private documents, bulk backlog or paused source recovery.')
write('title02-release-gate.json', {'revision': revision, 'approved': True, 'images': images,
    'new_contract_activation': False, 'authorization_evidence': evidence,
    'authorization_artifact_sha256': sha('title02-authorization-20261020.json'),
    'pr': 90, 'merge_commit': merged['mergeCommit']['oid'], 'ci': ci['statusCheckRollup'],
    'rollout_script_sha256': sha('title02-rollout.py')})
names = ['title02-six-intent-controller.py', 'title02-jev-proposed-scope.json',
         'title02-proposed-activation.json', 'title02-restored-scope-preflight.json',
         'title02-' + revision[:12] + '-git-manifest.json']
write('title02-six-permission.json', {'revision': revision,
    'full_candidate': read(names[-1])['full_candidate'], 'images': images,
    'input_hashes': {name: sha(name) for name in names},
    'host_wrapper_sha256': sha('title02-six-intent-host.py'),
    'initial_six_public_intents_authorized': True, 'authorization_evidence': evidence})
print(json.dumps({'revision': revision, 'release_gate': sha('title02-release-gate.json'),
                  'six_permission': sha('title02-six-permission.json')}))
