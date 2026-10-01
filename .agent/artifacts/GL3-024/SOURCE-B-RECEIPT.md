# GL3-024 source worker receipt

Candidate worktree: `gl3-024-source`  
Branch: `feat/gl3-024-cultivation-source`  
Base/current HEAD: `118d4197d0091ae73564a38130b4e0c20e72509d`  
Mutable state: only isolated `gl3_024_source_test` in the integration test; no acceptance database writes. No commit, push, merge, deployment, or production runtime change.

## Implemented boundary

Added one official source: `ma-ccc-cultivation-applications` / `ma-cultivation-applications`, direct CCC whole-snapshot JSON. Retrieval is fixed-host/path HTTPS, no credentials/redirects, 10 MB, 2,500 rows, 30-second deadline, snapshot age at most 30 days, and active application-event age at most 120 days. It validates row/schema bounds, consistent source update date, future/malformed dates, duplicate cultivation application identity, and exact cultivator type. No pagination exists because the endpoint is a single whole-file export.

Stable observation identity uses `APPLICATION_NUMBER`, falling back to `LICENSE_NUMBER`; changed status/dates update evidence without changing that identity. `SUBMITTED_DATE`, `ORIGINAL_SUBMITTED_DATE`, creation/approval/denial, snapshot update, final licensure, commencement, start/expiry, suspension, surrender, and revocation facts remain distinct. New Signals require a dated recent `PENDING` or `REOPENED` application, named applicant, complete Massachusetts physical establishment site, official citation, and no affirmative issued/operational/closed lifecycle evidence. Approved, stale, withdrawn/nonactive, missing-site, and lifecycle-conflicted applications remain retained evidence without a new-facility Signal.

Only whitelisted company/site/application/lifecycle fields are retained. `BUSINESS_EMAIL` and `BUSINESS_PHONE` remain labeled as CCC applicant-business contacts, with no buyer/decision-maker claim. EIN, mailing address, personal contacts, background, financial, and unrelated CCC fields are excluded. The source snapshot hash is separately retained as evidence extraction provenance; row evidence hashing includes whitelisted semantic facts only. Cultivation Signals identify the organization as an applicant and preserve UNKNOWN construction, operations, load, rental need, buyer, ownership, and authority. No area/license class is converted to MW.

The admitted subject and source title are company-first. The unmodified shared title helper can consume the explicit `applicant_org:` evidence field. Existing city/data-center/O&G source priority rules are untouched; this is one ordinary source path, not an alternate UI/watch feed.

## Public source check

Endpoint: `https://masscannabiscontrol.com/resource/l_applications_all_details.json`  
Publisher notes: `https://masscannabiscontrol.com/open-data/data-catalog/`

Two final direct adapter calls ran with the worktree interpreter and `PYTHONPATH=backend/src`:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend\src')
python -c "from datetime import date; from gridlens.ingestion.registry import load_registry; from gridlens.ingestion.adapters.ma_cultivation import retrieve; s=next(x for x in load_registry() if x['id']=='ma-ccc-cultivation-applications'); a=retrieve(s,today=date(2026,10,1)); b=retrieve(s,today=date(2026,10,1)); print(len(a),a[0]['source_snapshot_hash'],a[0]['source_snapshot_hash']==b[0]['source_snapshot_hash'])"
```

Both calls returned 452 exact cultivator rows and the same 8,075,059-byte snapshot SHA-256 `a46b79846534783ab78121e4a2acfb6dc30c10207bfc7d7af153efa9c8d637f3`; status counts were 398 approved, 2 pending, and 52 reopened. `CCCLastUpdated` was 2026-09-22. The rule assessment accepted 11 rows as dated applicant/site investigation Signals for the 2026-10-01 as-of date. This is local source parsing/assessment, not live database persistence.

Access detail preserved: an initial direct request with HTTPX's default/unlabelled user agent returned HTTP 403. An ordinary public request with a descriptive `User-Agent` returned HTTP 200; the adapter uses `GridLens public-data reader/1.0` and two later full reads succeeded. No credentials, challenge-solving, or security bypass were used. If public GET is denied again, retrieval fails visibly and retains prior evidence. The CCC catalog says its records are self-reported and does not guarantee completeness, accuracy, or timeliness.

Example from both successful snapshots: `MCN284034` / license `MC284034`, Rhythm of Life Cannabis LLC, `PENDING` / `IN PROCESS`, submitted 2026-09-03, original submission 2026-06-15, physical site 616 Douglas Street, Uxbridge, MA 01569. Event label: `Application resubmitted date`. This application event proves no construction, current work, operations start, capacity, rental demand, or authority.

## Focused deterministic validation

Interpreter used: `C:\Users\nrsan\Nucleus\02_Projects\GridLens\gl3-023\backend\.venv\Scripts\python.exe`; imports resolved from this worktree's `backend/src/gridlens/__init__.py`.

- `python -m pytest backend/tests/unit/test_ma_cultivation.py backend/tests/integration/test_ma_cultivation_ingestion.py -q` — exit 0, 15 passed.
- `python -m ruff check` on all 10 changed Python source/test files — exit 0, all checks passed.
- `python -m mypy --config-file backend/pyproject.toml` on the changed typed source modules — exit 0, no issues in 6 source files.
- `git diff --check` — exit 0.
- Integration uses only isolated `gl3_024_source_test` with the standard distinct app/test DB safety guard. It verifies one pending Signal plus an approved historical row, durable source facts with no EIN, UNKNOWN power/supply, exact replay without duplicate evidence, and preservation of prior state when retrieval fails. No acceptance database was written.

## Attempts and known limits

The first integration collection attempt failed because the integration test imported a unit-test module as a package; fixtures are now self-contained. The initial DB guard correctly refused to run while the controller had app/test URLs temporarily aliased to `gl3_024_source_test`; after the controller separated the scratch app DB and test DB, the original strict safety check remained and the focused integration passed. One intermediate assertion expected a fixture contact value that the fixture did not supply; the fixture now supplies an expressly public business contact and verifies its retained role and EIN exclusion. These failures and repairs did not touch acceptance data.

The CCC export is a whole snapshot, not an event log; polling can observe only what CCC exposes at retrieval time. It does not document a row-specific detail URL or completeness guarantee. The adapter cannot establish facilities outside the listed physical locations, all new construction, load or power gap, rental need, project authority, or reliable update latency. The controller still owns exact-candidate integrated gates, live acceptance-database ingestion/replay, and final review after serial integration with the presentation/UI changes.

## Changed files owned by B

- `backend/src/gridlens/ingestion/adapters/ma_cultivation.py` (new)
- `backend/src/gridlens/ingestion/adapters/__init__.py`
- `backend/src/gridlens/ingestion/adapters/retained_permits.py`
- `backend/src/gridlens/ingestion/registry.py`
- `backend/src/gridlens/ingestion/service.py`
- `backend/src/gridlens/domain/permit_interpretation.py`
- `backend/src/gridlens/domain/signal_admission.py`
- `backend/src/gridlens/intelligence/buying_chain_extraction.py`
- `backend/tests/unit/test_ma_cultivation.py` (new)
- `backend/tests/integration/test_ma_cultivation_ingestion.py` (new)
- `config/sources/registry.v1.json`
- `docs/sources/ma-ccc-cultivation-applications.md` (new)
- `docs/sources/coverage.md`

Frozen for controller serial integration. `.agent/packets/GL3-024.md` was supplied by the controller and is not a B edit. The builder has not committed or self-certified parent completion.
