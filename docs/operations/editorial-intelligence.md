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
Final selection retains these explicit human judgments. The bounded AI assessment is
advisory: exact retained factual excerpts and premise quotations, investigative
questions for implications/angles, citation checks and rejection of new quantitative
claims. Arbitrary prose cannot be proven true mechanically; an operator must verify
all reasoning. AI never grants clearance. The existing OpenAI brief credentials/model
are reused; missing credentials or invalid output produce an explicit unavailable
state. Assessments are retained against their evidence version in existing PostgreSQL.
Published PGR metadata supplies coverage when available; unavailable history is
unknown coverage, never a claim of novelty.

## Operator use

1. Open GridLens → Menu → **Editorial review**. Inspect retained evidence and its
   original source/date. Ineligible sources cannot enter the review projection.
2. Request an editorial assessment, then approve, reject or request more evidence.
   Approval requires source-supported factual excerpts, relevance, public-only and
   classification attestation. This does not establish a commercial Signal or Lead.
3. Decisions are append-only in existing PostgreSQL, with an insertion sequence,
   evidence ID/hash, server timestamp and session fingerprint. Shared-password auth
   has no named user identity; the fingerprint is not a claim of a named reviewer.
   Changed evidence invalidates clearance. Rejection and request-more-evidence withdraw it.
4. PGR's local Research screen and local Hub Research Inbox synchronize automatically
   through authenticated server connections. They preserve reviewed work during an
   outage and require current exact-version clearance before creating new content.
5. Choose **Develop outline** or **Create draft** deliberately. PGR outlines remain
   outside published Markdown; LinkedIn retains its existing review/approval gates.
   No article, post or email is sent automatically.

## Runtime and compatibility

Migration `0019_editorial_decisions` extends the existing database. Applying it to
production is a deployment action, not performed by this PR. No new database service,
news scraper, broker or orchestration framework is introduced.

`GET /api/editorial/candidates` preserves `2g-editorial/1`. The normal transport is
`GET /api/editorial/sync`, a `2g-editorial-sync/1` envelope around that unchanged feed,
with exact-version clearances and separately labeled advisory assessments. Resolve
`GET /api/editorial/clearance/{observation UUID}` before drafting: absence from the
ranked top three is not revocation. All routes require existing session auth; mutation
routes also enforce the existing origin check. Responses are private/no-store.

`config/policies/editorial-contract.mjs` and `editorial-sync.mjs` are canonical.
Consumer copies must remain byte-identical and use the same fixtures. Server-only
transport uses one configured origin, no redirects, bounded responses/timeouts and
in-memory session renewal. Passwords never enter consumer browser bundles.

Set `GRIDLENS_ORIGIN` in the local PGR server environment; the Research screen signs
in using GridLens credentials. Set `GRIDLENS_ORIGIN` and `GRIDLENS_PASSWORD` in the
local Hub's existing private environment. This is one-time connection setup, not a
per-story file transfer. No credentials are committed. Hub remains loopback by default.

The legacy CLI export/import remains an emergency inspection/recovery mechanism.
Schema-valid files alone do not prove authenticated clearance; normal browser draft
actions resolve against GridLens. `EDITORIAL_REVIEWS_PATH` is no longer the API's
clearance authority. Do not use the old private clearance file as the operational ledger.

## Verification and acceptance limits

Current public Utility Dive records were acquired with the existing RSS adapter and
retained through `process_records` in an isolated demo database. The October 13 FERC /
Duke large-load transmission report was exercised through real browser review,
version-bound **test-only** clearance, authenticated PGR synchronization and outline,
authenticated Hub synchronization, deliberate drafting, double-click/refresh dedup,
and reload persistence. Its original source date and hash remain intact. This is real
source evidence with an isolated automated review decision, not human production approval.

The environment has no live model or production GridLens credentials. Live AI quality,
a named human's production clearance and production consumer connectivity remain
unverified. Missing model access was exercised as an explicit unavailable state;
synthetic model responses test citation/premise rejection, not provider quality.

Newsletter workflow `29OhUFcCwBmNQOh2` was independently re-read during continuation:
active version `d9ff3f5b-0df4-4b3b-9125-adde0dedc745`, Beehiiv subscriptions → Resend.
No email code, workflow, subscriber record, deployment or external publication changed.
