# Editorial intelligence v1

GridLens owns evidence, not publication. PGR owns long-form journalism; LinkedIn
Desk selects its own short-form subjects. monday.com remains CRM authority.
No qualification tier is changed by editorial selection.

## Verified architecture (2026-10-15)

Inspected default branches and open PR inventory. GridLens uses FastAPI/session
authentication, PostgreSQL evidence versions and a durable worker; registry adapters
cover news, permits and official development notices. Content hashes preserve changed
evidence; source health is separate from publication dates. Existing opportunity CSV
exports include commercial context and are unsuitable for editorial distribution.
The new exporter queries only Observation, Evidence, Source.

PGR uses Markdown, React/Vite and Vercel build/content gates. Hub LinkedIn Desk uses
localStorage, backup files and explicit review/approval states. Its old App mounted
n8n research and automatically created drafts; the companion Hub change removes that.

n8n `8tHi72i3SQvY2ubn` is active (latest retained execution 80267, October 14), with
keyword scoring, a public CORS-open webhook and stale-table fallback. Exact historical
misclassifications are retained in the negative fixture, labeled unverified.
`XaIHyZb8kBFqjtTf` is inactive. `29OhUFcCwBmNQOh2` is active: hourly RSS → Beehiiv
subscribers → Resend → article receipt after the loop. No retained recent execution
was available. Partial retries can duplicate sends; provider `neverError` can log a
failed batch as completed. No workflow was changed or executed.
`IawwZJPMWMthRMmT` is unavailable through the connected tool.

PGR #44 head ea96040 conflicts and its Vercel check failed. Companion PGR changes
adopt its product boundary without deleting current operational documentation.
Hub #20 head 8095577 is mergeable, docs only, no checks; its local/Fleet/CRM requirements
remain separate and unchanged. Other open work (GL3 #66/#67, PGR #46, Hub #12/#19)
is not included in this integration.

## Contract and clearance

`2g-editorial/1`: generatedAt, up to three items, and rejected IDs/reasons.
The executable consumer validator is `config/policies/editorial-contract.mjs`,
vendored byte-for-byte into both consumers; the same real-source historical test
fixture verifies compatibility. Export time never refreshes a source date.

Each item has stable observation ID, title, original HTTPS URL, publisher, source
type, publication and first-seen dates, null material-change date (not established),
evidence ID/hash/date, geography, industry, event classification, source-reported
facts with evidence references, interpretations, hypotheses, unknowns, commercial
and technical implications, editorial angles, why-now, article type, confidence,
evidence quality, score and explicit approved-public eligibility.

Source-reported facts are exact retained quotations, not independently verified
truth. Human review must verify factual support and contextual classification;
"public source" alone is not publication clearance. No private notes, CRM/customer
intelligence, buying-chain contacts or internal pursuit research may be entered in
review text. Arbitrary fields are rejected, never forwarded. Clearance is bound to
one evidence hash. The registry source must be credential-free with retention terms
and an HTTPS endpoint matching the evidence host; off-host references fail closed.

Eligibility rejects missing evidence/source/date, modified hashes, unsupported fact
or change quotations, restricted content, non-US scope, future/stale dates (>30 days)
and duplicate IDs/canonical URLs. Current implementation deliberately cannot refresh
an old story based on an unverified material-change assertion.

Scoring: five reviewer dimensions 0–3 (reader value, specificity, significance,
originality, technical relevance), plus evidence (primary 3, reported 1) and age
(≤7 days 3; ≤14 days 2; otherwise 1). Reader value, specificity and significance
must each be ≥2; total ≥14, confidence medium/high, top three only. Confidence means
source support and known limitations, never sales qualification or a probability.
This is bounded **human editorial judgment**, not an implemented AI judge. Rejection
reasons remain in the export. `recentIds` suppresses recently used events; automatic
cross-product publication-history synchronization is not implemented.

## Operator use

1. Use the authenticated GridLens evidence view to inspect current retained evidence.
2. Create a private JSON clearance file outside Git. Top-level keys:
   `version: "2g-editorial-review/1"`, `reviews: [...]`, `recentIds: [...]`.
   Each review must match `EditorialReview` in `domain/editorial.py`; its JSON Schema
   can be printed with `python -c 'from gridlens.domain.editorial import EditorialReview; import json; print(json.dumps(EditorialReview.model_json_schema(), indent=2))'`.
   The test fixture is historical test material, not a cleared live candidate.
3. Set `EDITORIAL_REVIEWS_PATH` in the existing private API environment, or run
   `python scripts/export_editorial.py --reviews /private/reviews.json --output /private/feed.json`
   using the existing backend runtime. Output must not already exist. No DB writes.
   `GET /api/editorial/candidates` requires the existing session and returns no-store.
   Missing/invalid clearance returns 503, never falls back to a private database dump.
4. Import the same JSON into PGR (`npm run editorial -- import /private/feed.json`)
   and LinkedIn Desk's Research Inbox. Both independently select candidates.
5. PGR outlines stay in ignored `.editorial/`; only a human-written, reviewed article
   moved into the existing content workflow can become a publication PR. LinkedIn
   drafts keep existing Boss Review/approval and manual-copy posting gates.

No new database, scraper, publisher or production scheduler is introduced. This is
an operator-reviewed export slice, not completed autonomous editorial discovery.
Live approved candidates, bounded AI assistance, a clearance UI, and evidence of
live end-to-end operation remain acceptance work; do not claim those from fixtures.

## Verification recorded in this branch

- Full backend suite on isolated PostgreSQL 18.6: 1,678 passed, 1 skipped,
  7 subtests passed (232.12s). Initial SQLite attempt was unsuitable for DB tests;
  it is superseded by this PostgreSQL run.
- Final focused exporter suite after superseded-evidence/URL hardening: 13 passed.
- Ruff passed; mypy passed across 98 source files.
- Identical serialized historical fixture accepted by both consumer validators;
  validator files matched SHA-256 across all three repositories.
- These tests use isolated databases and retained fixtures. No production DB,
  live cleared candidate, model provider or deployment acceptance is claimed.
