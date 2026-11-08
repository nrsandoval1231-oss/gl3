# Account-first Slice 1 validation — November 8

Base: `3e1982ce6b36b951a634b75333eb08d27d83a097`. Branch: `feat/account-first-curated-experience`. [Draft PR #187](https://github.com/nrsandoval1231-oss/gl3/pull/187). This is the single sanitized receipt; exact final-head review and CI are attached to that handoff. Application source is frozen at `5c4bfd9ed08098abbd5662b0c5971be191c92a03`; subsequent changes are evidence/checkpoint updates, the single local disposable-database name guard and contact spacing rules. [Engineering and recovery](../../engineering/account-first-slice-20261107.md).

All fixture businesses, people, amounts and contacts are **synthetic**. Reserved `.invalid`/`.test` hosts and 555 methods are not outreach targets. No authorized sanitized retained-data snapshot was available or accessed. No production deduplication, source coverage, SLA or automatic exhaustive need-alias reconciliation is claimed. No application provider execution, merge, deployment, production writes or credential changes occurred.

## Final local gates

Commands run with fresh process-local authentication, providers disabled, zero request budgets and task-owned loopback PostgreSQL 18.6. Secrets and raw authenticated traces are excluded from this folder. Windows equivalents match the existing gates; CI uses Linux/Node 22.

| Gate / exact command | Result |
| --- | --- |
| `cd backend; uv sync --locked --extra dev` and `npm ci --prefix web` | Locked installs passed |
| `cd backend; uv run ruff check src tests` | Passed |
| `cd backend; uv run ruff format --check src tests` | 562 files passed |
| `cd backend; uv run mypy src` | 262 source files passed |
| `cd backend; uv run alembic upgrade head; uv run alembic check` | Revision 0051; no drift |
| `cd backend; uv run pytest tests -n 4 -rs` | **5,055 passed, 3 skipped**, 548.85s |
| `npm run typecheck --prefix web; npm run build --prefix web` | Passed; Vite existing >500KB chunk advisory (520.88KB JS, gzip148.77KB) |
| `cd web; npx playwright test --project=regression --workers=4 --output=../.artifacts/account-first/browser-final` | **317 passed**, 1.5m |
| `npm audit --prefix web --audit-level=high` | Zero vulnerabilities |
| `cd backend; uv export --locked --extra dev --no-emit-project --format requirements-txt --output-file .artifacts/backend-requirements.txt` then `uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r .artifacts/backend-requirements.txt --disable-pip --no-deps --format json` | No known vulnerabilities |
| `uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r tools/brand/requirements.txt --format json` | No known vulnerabilities |
| `.venv-brand/Scripts/python.exe tools/brand/validate.py` | 216 assets; eight semantic AA pairs passed |
| `backend/.venv/Scripts/python.exe scripts/check_docs.py` | 110 documents, 522 local targets, 18 anchors passed after staging |
| `backend/.venv/Scripts/python.exe -m pytest web/acceptance/pursuits-release/test_seed_safety.py -q` | **32 passed** |
| `git diff --check` | Passed |

The three backend skips are individually: optional local NC access probe unavailable; Windows has no RLIMIT_AS; Windows symlink privilege unavailable. No other backend test was skipped. The final 317-test run includes the reviewed contact-selection/ranking repairs and CI fixture corrections; typecheck/build passed again after CSS-only contact spacing rules. Final CI reruns browser gates on the exact presentation head.

## Real API and PostgreSQL journeys

`cd web; npx playwright test -c acceptance/pursuits-release/playwright.config.ts` with `PURSUITS_RELEASE_REAL=1`, explicit private output/manifest paths, loopback origin and disposable databases: **1/1 passed, 45.9s** (spec 41.9s). Actual journey: Opportunities → account → second project page → detail → Back with 48 projects restored → Companies → same account → explicitly chosen need POST 201 → reload → same saved pursuit → Reports → **one browser Back to the exact saved-pursuit URL**. Lost task response retried with the same client key retained exactly one task. Exact reserved phone/email hrefs passed; Companies selects the permitted Asset00 contact despite a contactless first child and displays its project scope. No automatic outreach activity was written. End state: one pursuit, one task, one created activity event, zero outreach/contact-action events, zero call notes, and 2,098 synthetic read-model rows.

`cd web; npx playwright test -c playwright.rollup-real.config.ts` with `CUSTOMER_ROLLUP_REAL=1`, explicit loopback origin/private output and separate disposable database: **3/3 passed, 36.1s** at 1440×900, 768×1024, 390×844. Corpus: 2,098 synthetic read-model rows / 417 groups. This scale fixture directly publishes synthetic projections and is not proof of end-to-end production ingestion; separate canonical producer/identity tests cover consolidation. Accounts with 48 and 159 projects page independently. Three same-name identities remain visibly qualified. A valid same-child filter tuple succeeds and its contradictory tuple yields expected 404. Historical support remains labeled. [Rollup measurements](rollup-performance.json), [rollup manifest](rollup-manifest.json), [Pursuits manifest](pursuits-manifest.json).

Deterministic tests prove twelve documents/five supported aliases across three sites produce one account/three projects; amendment does not inflate counts; authoritative-ID conflicts and subsidiaries preserve identities/contact authority; one owner’s two campuses remain distinct; owner/operator/EPC roles preserve evidence without duplicating physical projects; withdrawal changes current grouping without erasing evidence/pursuits. Unknown and overlapping MW remain scoped/unknown. High-value missing-contact records remain eligible; document volume alone does not create relevance. Privacy is covered across alias, regeneration, refresh and export. Need aliases preserve inactive/history records, serialize concurrent creation, reject unsafe equivalence and refuse silent multiple-pursuit merges. These are synthetic bounded tests, not a retained-data census.

## Audit regressions

| Finding | Repair / retained evidence |
| --- | --- |
| F1: URL changes while accounts remain visible | Section render guards unmount Opportunities; Companies/Reports route tests |
| F2: expired child token stuck at25/26 | Read-time TTL, bounded fresh-open recovery, independent child pages; 404/409/session regressions |
| F3: hidden refresh mutates another section | URL ownership guards, abort/late-response protection; cross-section and Back tests |
| F4: CSV loses demand/why/action | Shared scoped export retains statement/class/basis/timing/why/action and permitted methods; formula protection |
| F5: real-Pursuits config/path and CI omission | Absolute config-relative directories; persisted journey integrated in existing browser CI with separate disposable DB/origin |
| F6: stale merged/deployed statements | Active canon/checkpoints reconciled with base source; dated production receipt remains history; current runtime unverified |
| F7: connection query routing overrides | Both seeders reject routing overrides and validate effective host/port before connecting;32 safety tests including rejected remote targets without network connections |

## Measured reference performance

Windows reference: Intel Core Ultra5 225F, 10 cores/logical processors, 31.5GiB RAM; Python 3.11.16, PostgreSQL 18.6, Node 24.21.0, uv 0.13.4, Playwright 1.63.0. Measured on frozen source `5c4bfd9e` before the final CSS-only spacing rules. One run on 2,098 synthetic rows; ten warm read-only iterations per interaction; nearest-rank percentiles in the same browser/backend process. The superseded backend run was stopped before measurement; final full backend/browser gates started only after all ten warm repeats completed. Independent focused review may have overlapped preparation. The separate rollup run occurred under full-gate load; its route timings are diagnostic. First authenticated shortlist-ready 800ms (n=1, fresh browser context, server/PostgreSQL cache unknown). This is not a full cold asset start.

| Warm interaction | n | p50 ms | p95 ms |
| --- | ---: | ---: | ---: |
| Account search |10|462|472|
| Account open |10|266|269|
| Nested project paging |10|153|154|
| Project detail |10|180|194|
| Companies search |10|408|416|
| Companies account open |10|246|260|

[Raw sanitized samples and metric labels](pursuits-performance.json). Persisted journey 9828ms; journey plus benchmark 40770ms. 150 mixed API samples p50/p95 = 92/318ms are diagnostic, not individual-endpoint SLAs. `pursuitNavigationReadyMs` 348ms measures pre-reload navigation; it must not be described as reload latency. No production latency guarantee follows.

## Screenshots of the running synthetic workflow

Twenty-five actual viewport captures; interaction tests above establish behavior. Default and account views were recaptured after final CSS-only action/counter fixes; [read-only recapture checks](screenshots/account-first-recapture-receipt.json) cover overflow, overlap, 44px actions, external calls and unexpected writes. Sources are collapsed by default. Desktop/mobile inspection confirms readable cards and usable controls.

- Default shortlist: [1648x928](screenshots/default-shortlist-1648x928.png) · [1440x900](screenshots/default-shortlist-1440x900.png) · [1280x800](screenshots/default-shortlist-1280x800.png) · [768x1024](screenshots/default-shortlist-768x1024.png) · [390x844](screenshots/default-shortlist-390x844.png)
- Account detail: [1648x928](screenshots/account-detail-1648x928.png) · [1440x900](screenshots/account-detail-1440x900.png) · [1280x800](screenshots/account-detail-1280x800.png) · [768x1024](screenshots/account-detail-768x1024.png) · [390x844](screenshots/account-detail-390x844.png)
- Project detail: [1648x928](screenshots/project-detail-1648x928.png) · [1440x900](screenshots/project-detail-1440x900.png) · [1280x800](screenshots/project-detail-1280x800.png) · [768x1024](screenshots/project-detail-768x1024.png) · [390x844](screenshots/project-detail-390x844.png)
- Same account in Companies: [1648x928](screenshots/companies-account-detail-1648x928.png) · [1440x900](screenshots/companies-account-detail-1440x900.png) · [1280x800](screenshots/companies-account-detail-1280x800.png) · [768x1024](screenshots/companies-account-detail-768x1024.png) · [390x844](screenshots/companies-account-detail-390x844.png)
- Grouped Pursuits: [1648x928](screenshots/grouped-pursuits-1648x928.png) · [1440x900](screenshots/grouped-pursuits-1440x900.png) · [1280x800](screenshots/grouped-pursuits-1280x800.png) · [768x1024](screenshots/grouped-pursuits-768x1024.png) · [390x844](screenshots/grouped-pursuits-390x844.png)

## Independent review and recovery limits

Separate `gpt-6-astra/high` reviews independently exercised identity/contact privacy, physical grouping, aliases/concurrency, exact project targeting, 404/409 expiry, late responses, session cleanup and Reports navigation. Material findings were repaired and scoped checks repeated. Independent integrated source review covers `5c4bfd9ed08098abbd5662b0c5971be191c92a03` against base `3e1982ce6b36b951a634b75333eb08d27d83a097`, including the earlier full-diff review and subsequent repairs. The critic independently passed two persisted contact tests and eleven browser tests, verified responsibility ranking across/within projects and malformed data closure, and reported no remaining material source findings. Final evidence-only head attestation and exact-head CI are recorded in the draft PR handoff. Six `gpt-6-luna/low` builders ran; the lead runtime model identity is not exposed/certified.

Schema 0051 is additive. Empty disposable downgrade/re-upgrade passed; populated alias history blocks destructive downgrade. Roll back presentation/read projection using a schema-aware candidate retaining 0051 migration assets, alias/idempotency/privacy guards and persisted history. No retained-data migration, restore or rollback was executed. See the engineering record for practical recovery and internal-alias limitations.
