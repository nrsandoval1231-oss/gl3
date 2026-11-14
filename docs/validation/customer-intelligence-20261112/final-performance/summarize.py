"""Build the final matched comparison from immutable per-side receipts."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'summary.json'


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def ingestion(side):
    report = read(f'ingestion-{side}.json')
    return {
        phase['phase']: {
            'wall_seconds': round(phase['wall_seconds'], 3),
            'records_per_second': round(phase['records_per_second'], 3),
            'sql_statements': phase['statements'],
            'commits': phase['commits'],
            'new': phase['process_job_result']['new'],
            'changed': phase['process_job_result']['changed'],
            'unchanged': phase['process_job_result']['unchanged'],
        }
        for phase in report['phases']
    }


def rollup(side, *, lane):
    # The final baseline rerun used the already seeded corpus; the candidate
    # lane combines its initial seed and matched JIT-off measurements.
    suffix = 'fixed-' if lane == 'rollup-fixed' else ''
    report = read(f'rollup-{suffix}{side}.json')
    bodies = read(f'rollup-body-{suffix}{side}.json')
    return {
        'corpus': report['corpus'],
        'pages': {
            size: {
                'p50_ms': report['page_sizes'][size]['p50_ms'],
                'p95_ms': report['page_sizes'][size]['p95_ms'],
                'sql_statements': report['page_sizes'][size]['sql_statements'],
                'account_total': report['page_sizes'][size]['account_totals'],
                'json_utf8_bytes': bodies['page_sizes'][size]['json_utf8_bytes'],
                'returned_groups': bodies['page_sizes'][size]['returned_groups'],
            }
            for size in ('1', '25', '50')
        },
        'provider_ledger_rows': bodies['provider_ledger_rows'],
    }


def metadata(lane, side):
    return read(f'{lane}-{side}-metadata.json')['runs'][0]


def main():
    if OUTPUT.exists():
        raise SystemExit('Refusing to overwrite summary receipt')
    reports = {
        'baseline': {
            'commit': metadata('ingestion', 'base')['source_commit'],
            'source_manifest_sha256': metadata('ingestion', 'base')['source_manifest_sha256_before'],
            'source_unchanged': metadata('ingestion', 'base')['source_unchanged_during_run'],
            'ingestion': ingestion('base'),
            'rollup_commit': metadata('rollup-fixed', 'base')['source_commit'],
            'rollup_source_manifest_sha256': metadata('rollup-fixed', 'base')['source_manifest_sha256_before'],
            'rollup_source_unchanged': metadata('rollup-fixed', 'base')['source_unchanged_during_run'],
            'rollup': rollup('base', lane='rollup-fixed'),
        },
        'candidate': {
            'commit': metadata('ingestion', 'candidate')['source_commit'],
            'source_manifest_sha256': metadata('ingestion', 'candidate')['source_manifest_sha256_before'],
            'source_unchanged': metadata('ingestion', 'candidate')['source_unchanged_during_run'],
            'ingestion': ingestion('candidate'),
            'rollup_commit': metadata('rollup', 'candidate')['source_commit'],
            'rollup_source_manifest_sha256': metadata('rollup', 'candidate')['source_manifest_sha256_before'],
            'rollup_source_unchanged': metadata('rollup', 'candidate')['source_unchanged_during_run'],
            'rollup': rollup('candidate', lane='rollup'),
        },
    }
    if reports['baseline']['commit'] != '5ee2f30c2b1c9998063db1c6468d1f4e65f7ac2d':
        raise SystemExit('Baseline receipt does not match exact requested main commit')
    if reports['baseline']['rollup']['corpus'] != reports['candidate']['rollup']['corpus']:
        raise SystemExit('Matched rollup corpus counts differ')
    if reports['baseline']['rollup']['pages']['25']['account_total'] != reports['candidate']['rollup']['pages']['25']['account_total']:
        raise SystemExit('Matched account totals differ')
    reports['comparison'] = {
        'each_source_fingerprint_stable_during_measurement': (
            reports['baseline']['source_unchanged'] and reports['baseline']['rollup_source_unchanged']
            and reports['candidate']['source_unchanged'] and reports['candidate']['rollup_source_unchanged']
        ),
        'candidate_source_manifest_differs_from_baseline': (
            reports['baseline']['source_manifest_sha256'] != reports['candidate']['source_manifest_sha256']
        ),
        'candidate_rollup_page25_latency_ratio_to_baseline': (
            reports['candidate']['rollup']['pages']['25']['p50_ms']
            / reports['baseline']['rollup']['pages']['25']['p50_ms']
        ),
        'candidate_rollup_page25_payload_ratio_to_baseline': (
            reports['candidate']['rollup']['pages']['25']['json_utf8_bytes']
            / reports['baseline']['rollup']['pages']['25']['json_utf8_bytes']
        ),
        'candidate_rollup_page_sql_counts_constant_at_25_50': (
            len(set(reports['candidate']['rollup']['pages']['25']['sql_statements'])) == 1
            and len(set(reports['candidate']['rollup']['pages']['50']['sql_statements'])) == 1
            and reports['candidate']['rollup']['pages']['25']['sql_statements'][0]
            == reports['candidate']['rollup']['pages']['50']['sql_statements'][0]
        ),
    }
    OUTPUT.write_text(json.dumps(reports, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(reports['comparison'], indent=2))


if __name__ == '__main__':
    main()
