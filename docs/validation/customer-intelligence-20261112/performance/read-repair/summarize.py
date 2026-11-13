"""Derive the read-repair summary and artifact hashes from retained receipts."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parent
load=lambda name:json.loads((root/name).read_text())
summary={'commits':{r['side']:r['source_commit'] for r in load('metadata.json')['runs']},
         'corpus':load('base.json')['corpus'],'canonical':{},'api_setup':{},
         'assessment':'Baseline SQL count restored and historical candidate payload reduced; latency remains above baseline under shared live test/PostgreSQL load. No latency regression pass claimed.'}
for size in ('1','25','50'):
 b,a=load('base.json')['page_sizes'][size],load('repair.json')['page_sizes'][size]
 summary['canonical'][size]={
  'baseline_p50_ms':b['p50_ms'],'repair_p50_ms':a['p50_ms'],
  'baseline_p95_ms':b['p95_ms'],'repair_p95_ms':a['p95_ms'],
  'baseline_sql_counts':sorted(set(b['sql_statements'])),'repair_sql_counts':sorted(set(a['sql_statements'])),
  'baseline_json_bytes':load('base-body.json')['page_sizes'][size]['json_utf8_bytes'],
  'repair_json_bytes':load('repair-body.json')['page_sizes'][size]['json_utf8_bytes']}
 b,a=load('base-api-setup.json')['page_sizes'][size],load('repair-api-setup.json')['page_sizes'][size]
 summary['api_setup'][size]={'baseline_p50_ms':b['p50_ms'],'repair_p50_ms':a['p50_ms'],
  'baseline_p95_ms':b['p95_ms'],'repair_p95_ms':a['p95_ms'],
  'baseline_sql_counts':sorted(set(b['sql_statements'])),'repair_sql_counts':sorted(set(a['sql_statements']))}
(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir())
          if p.is_file() and p.suffix != '.log' and p.name != 'sha256-manifest.json'}
(root/'sha256-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(summary,indent=2))
