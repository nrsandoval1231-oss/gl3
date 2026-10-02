# GL3-026: full local intake and nationwide source discovery

The local app had been pointed at the small city/brief acceptance database: 19 retained needs, 18 visible after the commercial floor. This was an environment selection error, not a global opportunity limit. The new `gl3_026_app` database preserves that corpus and refreshes every configured source. It does not delete or replace the original databases. The former Windows cluster was started for a read-only inventory; its older databases remain preserved, not silently merged into the new corpus.

Base/main is `ce6b8fc688085c7a43f1bdefa35eeabeddb72903`, the merged PR15. New work is on `feat/gl3-026-national-intake`. Runtime remains local API8023/web5193; this is not cloud deployment.

## What changed

- Signals defaults to **All**, with SHOW, REVIEW and HOLD still available and their decisions retained. All does not bypass admission or the inclusive 300 kW commercial floor. Unknown-size Signals stay explicitly unknown.
- Source-sector filters consolidate overlapping source tags; Oil & gas remains distinct from Energy & utilities. Legacy `vertical` URLs still resolve. These are source-level tags, not assertions that every record belongs to an industry.
- The source selector uses authenticated source health instead of a hardcoded list. Texas RRC, Massachusetts cultivation, Taylor and new sources are selectable without a separate frontend edit.
- Firecrawl searched nationwide official permit routes and retained 24 discovery links. Boston was verified through its official CKAN API and added as source 19. Discovery links alone do not establish ingestion coverage.

## Actual acquisition and replay

All 18 previous enabled sources completed a real check. Five newly queued jobs were initially not lease-eligible; normal later checks succeeded without changing lease or backoff rules. That expanded the app to 7,741 observations and 1,147 visible Signal records.

Boston's official dataset advertised 664,565 historical rows. The adapter deliberately retrieves the rolling 90-day issue-date window, all statuses/types, using count-checked ordered pagination. The verified window contained 9,142 unique permit numbers, issued July 4–September 30, 2026: 7,328 Open and 1,814 Closed, with 16 explicit amendment references. Stable identity and citation filters use permit number; source row IDs are retained as provenance and excluded from semantic identity/hash. Updates outside the issue-date window are not monitored.

Real ingestion retained all 9,142 rows and admitted 20 Signals under the existing concrete-activity rules. Initial unchanged replay reported zero new/changed records and preserved exact hashes for observations, evidence, projects, needs, links and buying-chain claims. Totals became 16,883 observations, 16,922 evidence versions and 1,168 retained needs; the 35 kW historical Houston job remains outside the visible view.

Examples include temporary construction electrical services at 300 Terminal Road, laboratory renovation at 201 Brookline Avenue, and permit ETS1895395 at 32 Fruit Street, whose description explicitly lists two 375 kW temporary generators while a permanent generator is serviced. The permit does not establish a current sales opening, verified buyer, rental procurement authority or a calculated aggregate load. Applicant remains an applicant; personal names are not relabeled as companies.

## Limits and recovery

The first database clone used the cluster's WIN1252 default and the restore returned an error. That attempted database was preserved; the successful application clone explicitly uses UTF8. The current app's backup is retained in the ignored local artifacts directory. No credentials are committed.

Virginia DEQ's data-center register was readable through Firecrawl discovery and appears to contain 194 permit rows. Its pager footer did not mean only ten rows were captured. Direct HTTP returned an Akamai Access Denied page; a repeatable production acquisition path is not established, so no Virginia adapter is enabled. California, San Jose, Nashville, San Antonio and other discovered official routes remain candidates.

This is a larger current, source-backed corpus, not one million qualified Leads or all historical permits nationwide. The existing Signal/Prospect/Lead requirements are unchanged. News remains supplemental. No unsupported MW, utility delay, production date, current work status or buying authority is inferred.

Validation receipts, live project examples, source checks and independent review are in `.agent/artifacts/GL3-026`. Full final gates and exact review are recorded there after integration. Earlier failed attempts remain retained.

Final local gates: Ruff, mypy (58 source files), 546 pytest passes / one existing skip, frontend typecheck/build, clean and repeated migrations plus drift check, 18 browser passes and diff check. Four historical-corpus browser tests remain excluded under the prior scope; exclusions are in the exact command receipt. The initial full run caught one sort-key type annotation mismatch, repaired without changing behavior. A later real-record check added Boston-specific quoted temporary-generator ratings so an explicit 35 kW job is below the floor while the 375 kW example is visibly at/above the floor. No aggregate load or required MW is computed. The final full suite covers that correction.

Independent review found and repaired missing per-card/member decision labels and Boston structured permit facts/pursuit integration. Boston now uses the existing bounded pursuit trigger and research source policy. Its native applicant is exposed as a cited applicant field, with buyer authority unknown; ambiguous names do not become organizations.

The final row-level replay retained all 9,142 source records unchanged. All six domain tables were byte-for-byte equal under canonical row serialization, and every interpretation assessment/status/hash/version remained equal. One interpretation for ETS1870169 had an expired July 9 review date: only its attempt counter (4 to 5) and update timestamp advanced under the existing re-evaluation rule. Its display decision remains HOLD. The earlier full-table false-parity receipt is preserved; the new row-level receipt reconciles the current candidate without claiming that operational timestamps never change.

Independent final Sol review: PASS on manifest `1fb2e0617a52aa01628c991dd5965f57bef9fb48c2125892b683979030af0419`. Parent launch remains open. No merge or cloud deployment.

Changed product/documentation files:

- `.gitignore`
- `README.md`
- `backend/src/gridlens/api/app.py`
- `backend/src/gridlens/api/verticals.py`
- `backend/src/gridlens/domain/permit_interpretation.py`
- `backend/src/gridlens/domain/pursuits.py`
- `backend/src/gridlens/domain/signal_admission.py`
- `backend/src/gridlens/ingestion/adapters/README.md`
- `backend/src/gridlens/ingestion/adapters/__init__.py`
- `backend/src/gridlens/ingestion/adapters/boston_permits.py`
- `backend/src/gridlens/ingestion/adapters/retained_permits.py`
- `backend/src/gridlens/ingestion/registry.py`
- `backend/src/gridlens/ingestion/service.py`
- `backend/src/gridlens/intelligence/buying_chain.py`
- `backend/src/gridlens/jobs/worker.py`
- `backend/tests/integration/test_buying_chain.py`
- `backend/tests/unit/test_boston_permits.py`
- `backend/tests/unit/test_retained_permits.py`
- `backend/tests/unit/test_verticals.py`
- `config/sources/registry.v1.json`
- `docs/validation/gl3-026-national-intake.md`
- `web/src/app/App.tsx`
- `web/tests/first_path.spec.ts`
- `web/tests/project_cards.spec.ts`
- `web/tests/verticals.spec.ts`
