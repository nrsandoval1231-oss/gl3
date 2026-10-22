# Local Signal pipeline verification

Run the reproducible local check only after migrations are applied to a fresh,
isolated application database named `gridlens_verify_*`. The script refuses the
original `gridlens` database, test databases, and verification databases that
already contain observations, evidence, projects, needs, or jobs. It reads the
enabled source registry, queues each source through the existing queue, and
executes `gridlens.jobs.worker.run_one`; it does not substitute fixtures or call
adapters directly.

From the repository root in PowerShell:

```powershell
.\backend\.venv\Scripts\python.exe scripts\local_pipeline_check.py
```

The script writes a timestamped receipt under `.artifacts/GL3-013/` after every
source attempt and replay. An explicitly selected output path must not already
exist; previous receipts are preserved. Each source entry records normalized
records retrieved and parsed, new/changed/unchanged rows, failed jobs and parse
failures, overdue state, ordinary-worker attempt history, and source-linked
observation/evidence/project/need/change counts. Retrieved and parsed counts
describe adapter records that completed parsing, not HTTP responses or the
source's full population. A failed source has `null` record counts and a visible
error; it is never represented as an empty success. Replay uses the same queue
and worker and honors normal retry backoff. A nonzero exit means an initial or
replay job failed, or semantic content, counts, or morning-change evidence
changed.

Each database table digest hashes deterministically ordered retained rows. For
interpretations, the semantic content digest excludes only `attempts` and
`updated_at`, which are retry bookkeeping. A separate operational digest retains
all columns, including those counters and timestamps. The receipt compares both
digests before and after every replay, and also stores the canonical JSON count
and hash returned by the `/api/changes` handler. Retry bookkeeping may change the
operational digest while the semantic content digest remains stable. The local
result does not establish cloud operation, national coverage, or Lead
qualification.

## Older permit monitoring scope

Official Austin catalog metadata describes `statusdate` as the last date the
permit status or expiration was updated in its AMANDA database. The Austin
adapter unions permits issued in the last 30 days with commercial building
permits whose `statusdate` falls in the prior seven days. It excludes rows
without an issue date or with a future issue date, preserves the actual issue
date and status date, and applies exact count, pagination, byte, and row bounds.
The seven-day overlap tolerates a short interruption; edits older than that
window can be missed after longer outages.

Chicago's official Socrata `:updated_at` system field identifies when each row
was last updated. The adapter explicitly selects this normally hidden field and
unions qualifying permits updated in the previous two days with the 30-day
issue-date window. The query excludes null and future issue dates and update dates after the current UTC date, and uses the same count, pagination, byte, and row bounds.
Unfiltered dataset counts showed 255 updated rows in two days and 10,881 in 30
days. The final qualifying issue/update union returned 638 rows, including 71
older-issued permits. These counts are different populations. A longer outage can miss edits; a dataset-wide replacement
may exceed the cap and will fail visibly. Socrata's official documentation
explains system-field selection and that full dataset replacements update all
rows: [System Fields](https://dev.socrata.com/docs/system-fields.html).

Seattle exposes no separate per-row status-date field. Its `:updated_at` count
covered 193,257 rows during the recent two-day interval, exceeding the adapter's
bounded query cap. This is consistent with a bulk refresh, so the adapter does
not use it as a targeted change cursor. Seattle continues its bounded
recent-issue discovery query. Older status edits need a bounded query for
previously retained active permit IDs or a publisher lifecycle/status feed.
Austin's explicit `statusdate` remains its reliable update field; its
`:updated_at` count also reflects a bulk-wide refresh.

Official metadata and inspected counts are retained in the ignored
`.artifacts/GL3-013/socrata-monitoring-source-check.json`; the follow-up Chicago
field/query evidence is retained separately in
`.artifacts/GL3-013/socrata-chicago-updated-field.json`. Catalog endpoints are
Austin `https://data.austintexas.gov/api/views/3syk-w9eu.json`, Seattle
`https://data.seattle.gov/api/views/76t5-zqzr.json`, and Chicago
`https://data.cityofchicago.org/api/views/ydr8-5enu.json`.
