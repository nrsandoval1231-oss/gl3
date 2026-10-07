# GL3-029 final merge-validation checkpoint — October 7, 2026

**Do not merge: the required full browser suite has five failures.** Owner authorization to validate and merge is conditional on applicable gates passing. No merge or deployment occurred.

Tested candidate: `ecbcf03cdbde884a9f9c8d9506539753e09a1cb1`; product code unchanged from `92f7689544c6e72929615e3cad1a012fa38e5caf`. Source/config fingerprint `2f79ad311a5d9edd585237ff205b61f9a09731fa909159f4293c98f3a178778f`. See the [machine-readable receipt](gl3-029-merge-validation-20261007.json) for artifact hashes.

## Exact results

- Backend: **1,229 passed, one optional NC live-probe skip, one existing warning**, 147.09 seconds.
- Validator subset: **71 passed**, overlapping the full suite.
- Ruff, mypy (77 source files), frontend typecheck and build passed; npm audit reported zero vulnerabilities.
- Migration clean/existing/repeated upgrades and drift checks passed at `0014_pursuit_research_questions`; all **28 table inventories** preserved.
- Replay created zero questions and preserved the exact state hash; OpenAPI matched.
- Full browser suite: **37 passed, five failed, zero skipped/flaky**, 36.56 seconds. This comprises 36 regression passes and one of six live journeys passing.

## Browser failures

- **mobile health, ordinary news inbox, and browser history show actual local data states**: El Paso records absent; total zero.
- **live air documents retain equipment context without creating rental MW**: Georgia air example with reported power facts absent.
- **live data-center permit enrichment exposes attributed fields and organizations**: Georgia QTS ATL3 example absent.
- **real pursuits retain evidence gates and a saved owner call outcome across reload**: Legacy saved pursuits empty; Kramer scope required.
- **real conflicts, bounded refresh and mobile pursuit history work in the app**: Clayton/Stassney conflict examples absent.

These failures occur at missing-data prerequisites. They do not establish a product regression, but downstream behavior remains unvalidated. Five supplemental research-history browser groups do not replace the required health/inbox, air context, enrichment, saved call, refresh/conflict and pagination journeys. Assertions were not weakened or skipped. An earlier occupied-port startup failure is preserved separately; it ran no tests and is not counted among these five failures.

## Acceptance and next steps

Fresh five-category mechanical acceptance remains **5/5**, with six bounded UNRESOLVED questions and no promotions. This is regenerated public-source validation, not original retained PR23 proof. The focused positive-live-fact objective remains unmet. The original specification, PRD requirement 15 and R4 amendment permit meaningful bounded unresolved results; positive fact discovery is not an additional mandatory merge predicate. Unavailable-only acquisition is not meaningful negative proof.

El Paso acquisition previously returned HTTP 403. Georgia examples are absent; their accessibility has not yet been established. Legacy pursuit preparation uses a TDLR search-form POST; the prior narrow RRC download authorization does not authorize that separate form. Restore genuine retained prerequisites or investigate permitted public-source acquisition in isolated databases. Do not fabricate evidence or replace named live acceptance with synthetic fixtures without an explicit acceptance amendment.

Provider configuration/spending remains unauthorized; no credentials were configured or paid requests made. Branch-protection lookup returned HTTP 403, so protection requirements are unverified, not absent. Independent review identified the failed full-browser gate as a merge blocker. Further preparation and validation are pending. No external commercial outreach or cloud deployment occurs.
