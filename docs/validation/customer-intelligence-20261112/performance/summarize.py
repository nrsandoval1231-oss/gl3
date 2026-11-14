"""Recompute the matched report from retained JSON; never query or mutate a database."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
read = lambda name: json.loads((ROOT/name).read_text())
base, candidate = read('ingestion-base.json'), read('ingestion-candidate.json')
rows = []
for before, after in zip(base['phases'], candidate['phases'], strict=True):
    assert before['phase'] == after['phase']
    rows.append({'phase': before['phase'], 'baseline_wall_seconds': before['wall_seconds'],
                 'candidate_wall_seconds': after['wall_seconds'],
                 'observed_candidate_over_baseline': after['wall_seconds']/before['wall_seconds'],
                 'baseline_statements': before['statements'], 'candidate_statements': after['statements'],
                 'baseline_commits': before['commits'], 'candidate_commits': after['commits'],
                 'baseline_trigger_calls': before['trigger_calls'], 'candidate_trigger_calls': after['trigger_calls']})
page_rows = []
before, after = read('rollup-base.json'), read('rollup-candidate.json')
bbody, abody = read('rollup-body-base.json'), read('rollup-body-candidate.json')
assert before['corpus'] == after['corpus']
for limit in ('1','25','50'):
    b, a = before['page_sizes'][limit], after['page_sizes'][limit]
    page_rows.append({'page_size': int(limit), 'baseline_p50_ms': b['p50_ms'], 'candidate_p50_ms': a['p50_ms'],
                     'baseline_p95_ms': b['p95_ms'], 'candidate_p95_ms': a['p95_ms'],
                     'baseline_sql_counts': sorted(set(b['sql_statements'])),
                     'candidate_sql_counts': sorted(set(a['sql_statements'])),
                     'baseline_json_bytes': bbody['page_sizes'][limit]['json_utf8_bytes'],
                     'candidate_json_bytes': abody['page_sizes'][limit]['json_utf8_bytes']})
summary = {'ingestion': rows, 'rollup_corpus': before['corpus'], 'rollup': page_rows,
           'provider_ledgers': {'base': bbody['provider_ledger_rows'], 'candidate': abody['provider_ledger_rows']},
           'source_checks': {},
           'assessment': 'Observed additional SQL and payload costs. Shared-load timing samples do not establish an isolated regression bound; no no-regression acceptance is claimed.'}
for lane in ('ingestion','rollup'):
    metadata = read(f'{lane}-metadata.json')
    summary['source_checks'][lane] = [{'side':r['side'],'commit':r['source_commit'],
        'source_unchanged_during_run':r['source_unchanged_during_run'],
        'manifest':r['source_manifest_sha256_before']} for r in metadata['runs']]
(ROOT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ROOT.iterdir()) if p.is_file() and p.name != 'sha256-manifest.json'}
(ROOT/'sha256-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(summary,indent=2))
