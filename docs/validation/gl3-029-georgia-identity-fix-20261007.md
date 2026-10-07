# GL3-029 Georgia identity correction — October 7, 2026

**Latest full browser run: 40 passed, two failed, zero skipped/flaky, 38.42 seconds. Do not merge.** The remaining failures are the legacy saved-call and conflict/refresh/history journeys; TDLR public-search form authorization remains pending. The Georgia failures are resolved without changing browser assertions or weakening site matching.

Product candidate: `aa7a3464aa8f1dc681e6c37f08ed6d60df00a483`.
Source/config fingerprint: `e7c6fbd2674f275a94cda565a4faf83348c51c5be4cda4865219d0ad38cf825a`.
The tests ran against these exact source changes before the commit was recorded. No further product changes followed. [Safe receipts and artifact hashes](gl3-029-georgia-identity-fix-20261007.json).

## Root cause and minimal correction

The initial bounded Georgia run stopped on `926258-nar/download`. Two targeted diagnostic GETs retained the listing and exact PDF. The listing says **Southern Natural Gas - Ellerslie Compressor Station**, location **Ellerslie**, application **926258**. The official narrative says **Southern Natural Gas Company, LLC - Ellerslie Compressor Station**, with City **Ellerslie**. This is the correct facility/site; the listing was not pointing to unrelated evidence.

The existing normalizer strips legal terms including `co` and `llc` but omitted `company`, so ordered facility-token matching failed. Its separate application-number expression also did not recognize the plural `Application #s` label. The fix only adds `company` to the existing legal-term set. The application expression is unchanged; the record binds through exact facility tokens plus independently required location. No fuzzy match, relaxed station identity, project merging or source substitution was added.

Three new extraction tests reproduce the legal-name variation and reject a different station and different city. Before the fix: **one failed, two passed**. After: **three passed**. Independent adversarial review found no material evidence-boundary issue.

## Real adapter and canonical ingestion

The corrected ordinary adapter retrieved **18 records with 38 public GETs in 37.90 seconds**, with zero models and $0 provider cost, inside its existing source bounds and a 180-second outer run limit. This was one bounded revalidation after diagnosis; raw response hashes and source excerpts are retained locally, not published as full documents.

QTS ATL3, Augusta, application SIP-30169 (native record `6aaae66ddfc92ac4cd31cd97`), was selected from that real result and processed through normal canonical ingestion in the isolated browser database. One accepted Signal was created, retaining narrative/draft evidence and reported equipment context. The unchanged browser assertions confirmed **required MW remains null and supply remains Unknown**, and that organization attribution does not invent people/project assignments/public contacts.

The two now-passing browser tests are:

- `live air documents retain equipment context without creating rental MW`
- `live data-center permit enrichment exposes attributed fields and organizations`

This is source-ingestion/browser prerequisite recovery, not a positive autonomous missing-fact resolution or an original retained PR23 corpus claim.

## Final validation on the correction

- Backend: **1,232 passed, one optional NC live-probe skip, one existing warning**, 150.49 seconds.
- Validator subset: **71 passed**, overlapping the full suite.
- Ruff, mypy, frontend typecheck/build and audit passed; audit reports zero vulnerabilities.
- Clean, populated, repeated migrations and drift checks passed; all **28 table inventories** preserved at head `0014_pursuit_research_questions`. No migration changed.
- Full browser: **40 passed, two failed**, zero skipped/flaky. Both failures remain missing legacy research prerequisites, not waived assertions.
- OpenAPI matched exactly.

## Replay timing is explicit

Two initial diagnostic assertions incorrectly expected zero scheduling at current wall-clock time. Their failed receipts are preserved. The O&G questions had reached their persisted one-hour bounded-transient retry times (04:11:37/38 UTC); scheduling two retry-index-1 questions at 04:23 UTC is expected behavior, not duplicate work while fresh. One diagnostic also used an incorrect model attribute name; it rolled back without persistent changes.

The final check uses the scheduler's existing `now` argument to exercise both actual receipt boundaries: **zero questions and identical state hash within the freshness window**, then exactly two eligible O&G retries after expiry. Every dry-run transaction rolls back, with original persisted hash `39d69cdc8a92acec303346f08445766c6308258dfa2b9d97aba0492fddcee44a` unchanged. No acquisition ran, no historical timestamp/budget was rewritten, and no forever-fresh claim is made.

## Remaining gate

`real pursuits retain evidence gates and a saved owner call outcome across reload` and `real conflicts, bounded refresh and mobile pursuit history work in the app` still fail because legacy saved research rows are absent. Genuine Kramer/Stassney city evidence is prepared; the ordinary worker's TDLR public-search POST remains outside the previous RRC-only exception. Permission is pending. No TDLR form, outreach, paid-provider configuration, merge or cloud deployment occurred.

Historical diagnosis, bounded revalidation, canonical QTS import and replay-window procedures are retained as non-executable `.py.txt` records in `docs/validation/procedures/`. They are specific to this isolated validation and do not authorize future acquisitions or production writes.
