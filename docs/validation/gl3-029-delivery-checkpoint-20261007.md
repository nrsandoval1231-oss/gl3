# GL3-029 — delivery checkpoint, October 7, 2026

The owner requested publication of completed work to GitHub. The existing
[GL3-029 draft PR24](https://github.com/nrsandoval1231-oss/gl3/pull/24) is the delivery;
no duplicate PR, deployment, credential configuration or paid research is part of
this checkpoint. The subsequent owner instruction, “validate and merge,” authorizes
merge only after applicable validation gates pass. Final validation completed with five required browser failures; merge remains blocked. See [exact results](gl3-029-merge-validation-20261007.md).

## Published work

- Product implementation, migration, tests and frontend are on branch
  `feat/gl3-029-autonomous-pursuit-research`.
- Tested product code: `92f7689544c6e72929615e3cad1a012fa38e5caf`.
  Source/config fingerprint:
  `2f79ad311a5d9edd585237ff205b61f9a09731fa909159f4293c98f3a178778f`.
  Subsequent checkpoint commits change documentation and historical procedure records only.
- Reusable collection/ingestion/archive tooling: `scripts/regenerate_pursuit_corpus.py`.
- Canonical baseline/research/replay validation: `scripts/validate_pursuit_research.py`.
- [Five-category report](gl3-029-five-category-20261007.md) and its JSON companion:
  5/5 mechanical cases, six unresolved questions, exact tests and 46 artifact hashes.
- [Focused live proof](gl3-029-live-fact-proof-20261007.md) and its JSON companion:
  two real native refreshes, no new resolving fact, preserved history and 17 artifact hashes.
- Canonical README, current state, architecture, operations and decisions include
  implementation, review findings and the distinction between local validation and production.

The exact temporary procedures used for the corrected focused proof and five-category
browser checks are archived as non-executable text for review/reproducibility:

- [Focused actual-worker procedure](procedures/gl3-029-live-fact-proof-20261007.py.txt).
- [Actual-database browser procedure](procedures/gl3-029-five-category-browser-20261007.cjs.txt).

These are dated, database-specific validation records, not general operational launchers.
Do not run them against original data or with newly enabled paid access. In particular,
the historical proof harness's boolean `new_evidence and resolved` is not sufficient
for a future positive claim: supporting evidence must causally establish the resolved
answer. The recorded outcome is false. Any paid proof needs separately approved limits
and a launcher enforcing those limits.

## Current proof and Firecrawl status

The positive live objective remains **unmet**. The available native Chicago route
returned unchanged evidence, so RESEARCH/Signal stayed unchanged. The final existing
application check found no Firecrawl credential or search-cost reservation and a $0
question budget. The owner subsequently confirmed possessing a key; possession is
not secure transmission, configuration, or permission to spend. No key was configured
and no paid provider call was made by this checkpoint.

Verified application fields:

| Environment variable | Default | Meaning |
|---|---|---|
| `FIRECRAWL_API_KEY` | Unset | Credential supplied securely to the worker process |
| `FIRECRAWL_SEARCH_COST_USD` | Unset | Positive USD reservation per search request; not per result or credit |
| `FIRECRAWL_SCRAPE_COST_USD` | Unset | Optional paid extraction reservation |
| `AUTONOMOUS_RESEARCH_MAX_COST_USD` | `0` | Accumulated reservation cap per question |

The proposed, **unapproved** next-proof limits were two selected questions, three
searches per question, ten candidate URLs, five retrieval attempts, 750,000 bytes per
document, 180 seconds per question, and a 420-second whole-run limit. A proposed
$0.10/search reservation and $0.30/question ceiling imply a $0.60 aggregate reservation.
These are accounting policy proposals, not verified Firecrawl prices or guaranteed
provider billing caps. Paid scraping would remain unset and model calls zero.

No general secure-secret-entry control for this saved executor was verified through
the exposed tools. Do not paste the key into chat or commit it. Establish a supported
secure injection path and obtain explicit bounded-usage approval first. The old
`/tmp/gl3-regen-run.py` deliberately strips provider keys and forces $0; it is not a
paid-proof launcher. Settings must precede process startup and new question creation;
historical question budgets must not be rewritten. Preserve daily counters and admit
only the explicitly approved additional jobs.

## Retained locally, deliberately excluded from Git

All are in the saved executor; this is retention, not a cloud-durability guarantee.

| Material | Retention path |
|---|---|
| Original public RRC snapshots and full parsed records | `.artifacts/rrc-drilling-download-20261007/` |
| Fresh permit collection and canonical ingestion receipts | `.artifacts/regeneration/collection-0218/`, `ingestion-final/`, `rrc-ingestion/` |
| Five-case pre/post database archives and inventories | `.artifacts/regeneration/five-run-restore/`, `five-post-restore/` |
| Focused-proof pre/post archives | `.artifacts/regeneration/fact-proof-retry-restore/`, `fact-proof-post-restore/` |
| Full validation logs, screenshots and native receipts | `.artifacts/regeneration/` |
| First invalid focused harness run and explicit correction | `.artifacts/regeneration/live-fact-proof/` |
| Corrected focused proof baseline/results | `.artifacts/regeneration/live-fact-proof-retry/` |

Original `.env`/authentication material remains outside Git and is neither copied nor
published. Full source files, database dumps, browser binaries, caches and logs are
not necessary PR source code; reviewable bounded receipts and their hashes are published.
The original and isolated databases are preserved. Earlier failed reports are not erased.

There are no unpublished completed product-code changes. A secure credential handoff,
approved paid-proof launcher and successful new-fact resolution are unfinished next
steps, not hidden deliverables. Historical PR23 corpus/browser proof remains distinct.
Keep PR24 draft until the required final gates pass. Merge is now conditionally
authorized; deployment remains excluded. Independent contract review found that
bounded meaningful UNRESOLVED results are permitted by the original specification,
PRD15 and the R4 owner amendment. The failed positive demonstration stays disclosed;
it is not itself a newly imposed positive-only merge predicate. Existing live browser
behavior coverage failed: 37 passed and five missing-data prerequisite failures. These gates remain mandatory.
