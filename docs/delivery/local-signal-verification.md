# Local Signal verification — GL3-013

This is a local checkpoint, not cloud acceptance, national coverage, seven scheduled cycles, or Lead readiness. Branch `verify/local-signal-pipeline` starts at main `a7ee3e4d22c5375481402c637d22c08eba59cbac`. Previously accepted GL3-010/011/012 local work is carried forward so this verifies the current pipeline. The original checkout, running app and database are preserved. The frozen design is preserved. A measured mobile overflow required two CSS declarations to let long source excerpts wrap without hiding content.

## GitHub failure

[Main run 36337199378](https://github.com/nrsandoval1231-oss/gl3/actions/runs/36337199378) never allocated a runner: both jobs have zero steps and runner ID 0. GitHub annotations cite failed account payments or a spending limit; they do not distinguish those alternatives. CI was not weakened. An owner billing review is separate from local code quality.

## Isolation and reproducibility

This run uses PostgreSQL 18 on loopback 55439: `gridlens_verify_20260927_final` for real-source application data, `gridlens_verify_20260927_final_test` for destructive integration tests, and `gridlens_verify_20260927_final_migration_test` for fresh migrations. The existing `gridlens` application database is not a test target. Credentials remain ignored. Isolated API/web use 8001/5174. The fresh-run receipt and gate logs are retained under `.agent/artifacts/GL3-013/`; original-source response bodies, screenshots and authenticated exports remain local under ignored `.artifacts/GL3-013/`.

## Remaining release gates

Cloud daily operation still needs restored hosted CI admission, authorized hosting/secrets, PC-off scheduler proof, seven measured daily cycles, alert/retry operations and cloud backup/restore proof. Source scope remains three city building datasets, one Georgia draft-air list, Federal Register, NC Commerce and six publisher feeds; it is not national permit coverage.

Prospects require activity-specific demand and suitable-supply evidence, timing and identity research. Leads additionally require auditable MW/duration/supply scenarios and buyer/commercial facts plus owner review. A permit, generator schedule, proposed campus capacity or unknown utility service does not alone establish a rentable gap. No records were promoted to improve counts in this slice.


## Final commands and results

All commands ran in `gl3-local-proof` or the indicated subdirectory after the final code edits. Setup used `uv sync --project backend --locked --extra dev`, `npm ci` in `web`, and the repository environment setup. PostgreSQL application, destructive test and migration databases are separate, newly created databases.

| Command | Result |
|---|---|
| `ruff check src tests ../scripts/local_pipeline_check.py ../scripts/export_review_sample.py` (backend) | PASS |
| `mypy src` (backend) | PASS, 30 source files |
| `alembic upgrade head` twice, then `alembic check` against the fresh migration DB | PASS; no drift |
| `python -m pytest tests -q` (backend, fresh test DB) | PASS, 205 tests; one dependency deprecation warning |
| `npm run typecheck` / `npm run build` (web) | PASS / PASS |
| `npm audit --audit-level=high` (web) | PASS; zero vulnerabilities |
| `npx playwright test` with API 8001/web 5174 | PASS, 3 tests, authenticated desktop/mobile plus grouping regression |
| `python scripts/local_pipeline_check.py --output .artifacts/GL3-013/final-live-run.json` | PASS; 12 fresh source runs and 12 replays |
| Live authenticated exports and desktop/mobile screenshots | PASS; unauthenticated API denied, no page errors, mobile width 390/390 |

## Fresh source counts and replay

Retrieved/parsed are normalized adapter records, not HTTP responses or complete source populations. All sources were reachable. Every row below had zero failed jobs, failed records, failed/pending interpretations and parse failures, and was not overdue after both runs. Before initial ingestion every fresh source was overdue, as expected.

| Source | Retrieved / parsed | New | Changed | Unchanged | Replay retrieved / parsed / unchanged | Replay new / changed |
|---|---:|---:|---:|---:|---:|---:|
| austin-building-permits | 1600 / 1600 | 1600 | 0 | 0 | 1600 / 1600 / 1600 | 0 / 0 |
| chicago-building-permits | 638 / 638 | 638 | 0 | 0 | 638 / 638 / 638 | 0 / 0 |
| construction-dive-news | 10 / 10 | 10 | 0 | 0 | 10 / 10 / 10 | 0 / 0 |
| dcd-news | 20 / 20 | 20 | 0 | 0 | 20 / 20 / 20 | 0 / 0 |
| federal-register-eis | 73 / 73 | 73 | 0 | 0 | 73 / 73 / 73 | 0 / 0 |
| georgia-air-draft-title-v | 18 / 18 | 18 | 0 | 0 | 18 / 18 / 18 | 0 / 0 |
| manufacturing-dive-news | 10 / 10 | 10 | 0 | 0 | 10 / 10 / 10 | 0 / 0 |
| mjbizdaily-news | 30 / 30 | 30 | 0 | 0 | 30 / 30 / 30 | 0 / 0 |
| nc-commerce | 14 / 14 | 14 | 0 | 0 | 14 / 14 / 14 | 0 / 0 |
| ogj-exploration-news | 25 / 25 | 25 | 0 | 0 | 25 / 25 / 25 | 0 / 0 |
| seattle-building-permits | 82 / 82 | 82 | 0 | 0 | 82 / 82 / 82 | 0 / 0 |
| utility-dive-news | 10 / 10 | 10 | 0 | 0 | 10 / 10 / 10 | 0 / 0 |

After both passes: **2,530 observations, 2,567 evidence versions, 87 project rows, 87 needs, 87 links, 87 changes, 2,530 interpretations**. All table semantic hashes and counts matched; the morning digest remained 87 entries with an identical hash. Interpretation retry counters/timestamps are excluded only from semantic hashes; separate full operational hashes retain their changes. No observation, evidence version, project row or morning entry was added by replay. The same unchanged API records produce the same 69 display cards.

The UI presents **87 Signal records as 69 cards**, including 19 Zilker event permits in one card. Database project rows and display cards are not verified distinct projects. The [34-card original-citation review](signal-card-review.md) covers 52 underlying records. All 52 records were reconciled by stable source/document identity into the final fresh run, and all reviewed facts matched the snapshot. Seven Chicago cards gained only the newly selected official modification-date line, changing their evidence hashes; all other sampled evidence hashes matched. This explicit difference is retained in the reconciliation receipt. Four Ascension permits describe one hospital project and two PACU permits another; therefore this sample contains at most 30 project candidates, with actual distinct-project count still UNKNOWN. Buyer and next-action gaps, weak rental hypotheses, and event dates are recorded individually in the table. No tier promotions were made.

## Bounded repairs and limits

Austin now unions the 30-day issue window with seven days of official status-date updates; Chicago explicitly retrieves its reliable row modification field and unions two days of updates. The final query included 1,294 older-issued Austin records and 71 older-issued Chicago records. Many are lifecycle updates, not new opportunities. Older status-change regressions cover adapter retrieval and persisted evidence. Seattle system timestamps reflected a 193,257-row bulk refresh, so that field is not a usable bounded update cursor. The source-specific remedy is a bounded recheck of retained active permit IDs; it is documented, not implemented here. Outages exceeding overlap windows can miss updates.

Other repairs: nullable publication-date export; source health counts; reproducible worker replay proof with full and semantic digests; isolated browser ports and actual authenticated live-record tests; two CSS wrapping declarations for a measured mobile overflow. Permit parsing remains in adapters, qualification in domain code, presentation in the web app. Accepted earlier GL3-010/011/012 work is carried forward from the original checkout, including Georgia permit ingestion and simple project cards. No new source or infrastructure was added in this verification slice.

Retained failures: the first local suite exposed an omitted optional Austin status date and was repaired; an initial proof harness treated interpretation retry bookkeeping as content changes and now reports both honestly; the mobile gate exposed overflow and was repaired. Earlier failing receipts remain available. A failed multi-ID sample query returned no records and was explicitly excluded; the corrected official 19-member Zilker response is the evidence.

Independent review targets the committed candidate, this report, the 34-card table and retained original-source captures. The review receipt is retained locally under `.artifacts/GL3-013/final-review.json` so post-review bookkeeping cannot change the reviewed commit. The PR records the exact accepted SHA.
