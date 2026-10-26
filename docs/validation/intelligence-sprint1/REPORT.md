# Intelligence Sprint 1 — evidence and remaining acceptance

> **Historical candidate report — nonauthoritative for current readiness.** These
> measurements and validation receipts describe the original PR125 candidate and
> its named local/staging environment only. They do not prove the current integrated
> candidate, deployed operation, present source/contact coverage, or owner approval
> to spend, mutate production data, or deploy. The owner-approved [Autonomous
> Intelligence Canon](../../product/AUTONOMOUS_INTELLIGENCE_CANON.md) governs
> current product behavior; its prohibition on manual correction and operator
> workflow routes supersedes candidate-era API descriptions below.

Repository: nrsandoval1231-oss/gl3. Base: 3ce9e8a (merged PR122).
Execution: six concurrent supported gpt-6-luna/low builders with exclusive file
ownership in one isolated worktree; independent gpt-6-astra/high review. No model
substitution. The running lead session's model was not programmatically switched.
Original wrapper/recovery checkouts were preserved. No production database,
deployment, merge, paid-provider activation or outreach was performed.

## What runs

Excel/CSV preview and immutable PostgreSQL staging, original row provenance,
explainable conservative company/project proposals, duplicate diagnostics,
history and batch rollback; canonical graph and contact assertions over existing
identity/evidence/correction models; bounded incremental company research in the
existing durable worker; exact-scope power scenarios; generated authenticated API
contracts and an existing-panel UI integration. The PR125 local staging notes are
preserved in [the historical Sprint 1 guide](../../operations/INTELLIGENCE_SPRINT1.md).

## Actual workbooks

All four workbooks were available in `C:\Users\nrsan\OneDrive\Desktop\Data Center`.
They were read in place and imported only into disposable loopback staging,
restored from a retained snapshot. Originals/private rows and detailed reports
remain in ignored `.artifacts/sprint1`; no private workbook values were committed.

| Workbook | Retained source rows | Invalid rows | Summary/metadata/empty normalized rows | Combined canonical matches |
|---|---:|---:|---:|---:|
| Cleanview.xlsx | 885 | 0 | 0 | 0 |
| DC Leads.xlsx | 2,077 | 0 | 0 | 0 |
| texas dc leads.xlsx | 486 | 2 | 0 | 0 |
| US_Data_Center_Project_Tracker_August_2026.xlsx | 1,072 | 2 | 62 | 0 |
| Total | 4,520 | 4 | 62 | 0 |

The 4,454 remaining source rows are unmatched assertions. Import matching did not
create or enrich any canonical opportunity. The tracker needs an explicit Developer
mapping because Developer and Owner are separate fields. Campus and IT capacity,
source units/ranges, and original completion dates remain distinct from temporary
power demand and a required-power date. Four unsupported power-value formats stay
visible errors rather than guessed values. Summary/guide rows never become projects.

Across these originals: 597 distinct normalized company-name assertions, 4,323
distinct project-name/site-field tuples, and 130 exact repeated raw rows across
files. These are source-string counts, not independently resolved companies/sites.
There are eight within-file exact duplicate groups and one probable-name duplicate
group. Original duplicates are retained; no sales opportunity reduction is claimed.
No supported canonical match means canonical conflict comparison is not applicable;
zero detected conflicts is not proof that source values agree. Replay retained four
batches and 4,520 rows without duplication. Both parser and PostgreSQL staging tests
exercise 25,000 synthetic records; this does not claim a real 24,750-contact import.

The final strict matcher leaves all unmatched real rows inactive. A real Texas
workbook batch was rolled back twice: one rollback event, unchanged four batches
and 4,520 retained originals. Only corroborated matches can expose imported contact
assertions; a company-only contact row may match without inventing a project.

## Existing-project benchmark and real vertical slice

The retained snapshot contains 1,903 projects/needs and 1,154 company identities.
The benchmark selected 25 eligible existing projects in latest saved-browse priority
order with a stable UUID tie-break. Six of 25 had canonical customer company links
(four distinct companies), and zero of 25 had usable published contact methods
before the trial. It is a snapshot benchmark, not a current production census.

One company in that cohort, EG AI, was then researched through the existing worker
using its public [company contact page](https://egai.us/contact/) and home page.
Actual local retrieval/extraction/persistence succeeded in 4.250 seconds. The result
was **one published company email route and two named roles without direct methods**,
each retaining source provenance. No person was promoted to a verified buyer.
The company email is a general route; mailbox deliverability and purchasing authority
remain unconfirmed. The independently verified mailbox count remains UNKNOWN.

The completed-job replay took 0.407 seconds, reused the job and retained the same
three contact entries. Both runs added zero governed paid-provider calls. Additional
provider API cost was zero for these trials; whole-platform billing is not measured.
A repeated benchmark after that single-company research showed published-route
coverage at 1/25 and named direct-contact coverage at 0/25. Do not extrapolate this
small targeted trial into population coverage or identity accuracy.

Real local authenticated API reads returned 200 for the company graph and contacts.
Actual 1648×928 desktop and 390×844 mobile UI inspection showed the same canonical
company/project, published route, source links, explicit unconfirmed authority,
and two named roles without methods. Reload persisted the result; mobile had no
horizontal overflow. The restored derived browse projection first rejected the new
code fingerprint (503); rebuilding it through the existing local saved-browse
service restored access. No production browse or source data was changed.

An original-row comparison across projects, needs, observations, evidence, company
and person identities, memberships, identity identifiers, buying-chain claims and
buying-chain evidence found zero deleted or changed original rows. The public trial
appended three claims and three buying-chain evidence rows. Staging appended only
its own tables; stronger accepted project/power facts were preserved.

## Review and validation record

Astra independently rejected the first source candidate, finding seven material
issues: conflicting import signals/domain hints; a weakened canonical source gate;
unsupported company relationships; retraction reinstatement; estimated supply labels;
raw-column collisions; and direct-job stale refresh. Repairs and regression tests
are part of the final candidate. Custom relationship directions remain explicitly
unverified operator assertions, with source quotes and current company identity
bindings; a current ledger entry is not an independently verified relationship.

Exact final commands/results, final review verdict and candidate SHA are recorded
in the PR description and the task's ignored validation/review receipts. Earlier
failing trials are retained rather than replaced with success claims. Unit and
database fixtures are synthetic; real workbook runs and the real public retrieval
are separately described above. No local test count establishes commercial readiness.

Controller checks at the repaired-source freeze: 73 focused unit/PostgreSQL/API
checks (including the existing direct-refresh regression); full browser suite 206
passed/1 skipped; Ruff/format/mypy; generated OpenAPI/types; web typecheck/build;
locked backend and npm dependency audits; 216 brand assets; repeated restored
schema upgrade and Alembic drift; maintained documentation links. The full backend
run and remote CI are reported separately in the PR; this paragraph does not turn
an in-progress or interrupted run into a pass.

## Open commercial and production gates

- Full Sprint 1/commercial P0 acceptance remains OPEN. The safe vertical slice is
  implemented; the whole mission is not complete.
- Workbook company/site reconciliation and official-source follow-up are still
  needed. Zero automatic matches is an unresolved usefulness gap, not high accuracy.
- Company/project match accuracy and false-positive contact rates require independent
  labeled samples; they remain UNKNOWN. No calibrated probability is reported.
- Buyer authority, independently confirmed mailbox deliverability, verified direct
  buyer contact coverage, rental duration/value and supported power supply remain
  unestablished where evidence is absent. No unknown supply becomes zero.
- Apollo API support, self-hosted Firecrawl installation, and durable independent
  mailbox verification are not implemented/activated in this candidate. Existing
  governed Firecrawl/OpenAI/Jev interfaces and settings are preserved.
- A changed mapping/normalization for an already-staged file produces an explicit
  conflict instead of silently reusing old normalized data. Review mapping changes
  in a fresh staging batch/database; there is no automatic production promotion.
- Production migration, authenticated production UI, operating cycles, live-provider
  budgets and commercial outcomes have not been validated by this task. No deploy.
