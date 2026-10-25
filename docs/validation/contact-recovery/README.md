# Contact intelligence recovery — 2026-10-25

This is a reviewed recovery increment, not acceptance of the full P0 commercial
coverage mission. No production records were read or modified, no deployment was
performed, and no paid provider was invoked. The configured localhost database
contains zero projects. Production coverage and improvement cannot be inferred
from synthetic regression fixtures or the empty local database.

## Diagnosis and repairs

| Layer | Finding | Repair |
|---|---|---|
| HTML normalization | `mailto:`/`tel:` destinations disappeared when labels said Email/Call | Preserve both label and literal destination; retain explicit Organization JSON-LD before stripping scripts |
| Extraction | Only narrowly phrased named-person methods were recognized | Extract explicitly company-attributed methods and self-hosted, exact-name Organization directories; preserve source quotes |
| Persistence | Claims and evidence already retain append-only contact history | Reuse those tables; do not create a competing address store |
| Refresh | Same-entity retained refresh could hide an unchecked verified contact | Carry current source-checked methods; retain stronger full-page relationship citations |
| Identity | Replacing a claim could create a fresh account identity | Carry identities only across identical project/entity, relationship quote, URL and supported source; preserve operator correction/retraction chains |
| API | Company account responses had no contact projection | Authenticated `/api/customer-accounts/{company_identity_id}/contacts` projection |
| UI | Company workspace omitted contacts | Compact Contacts & Buying Chain in existing account and opportunity panels, mail/call/source links, Research Required and retry states |
| Metrics | Named permit-listed people could look like buyers | Require a supported role, distinguish generic-only methods, publish explicit denominators |

Company matching never uses name equality to merge identities. All project
association, evidence currency, correction, regional eligibility and qualification
rules remain authoritative. Source verified means the method occurs in current
retained evidence; it does not claim email deliverability, a live phone response,
or confirmed purchasing authority.

## Model and discovery boundaries

`BuyingChainClaim`, `BuyingChainEvidence`, identity links, and runs remain the
persistent model. CompanyContact exposes company ID, person/name/title, affiliation,
buying role, email/phone methods, source URLs, observed/verified dates, categorical
evidence confidence, responsibility, and associated project IDs. Multiple methods
and contacts are supported. Duplicate projections union project/source references;
immutable claim/evidence history remains inspectable through existing history APIs.
Phone type stays unknown when not evidenced. A source URL is not automatically
labeled the company's official website. Purchasing authority remains unconfirmed.

Existing role classification covers construction/superintendent, electrical/energy,
commissioning, facilities/field operations, and procurement. It remains a
source-supported role classification, not a category-based assertion that a person
is the buyer for a particular power package.

The existing bounded public-research job can process supplied public URLs and
follow its permitted same-host contact/team links. This change adds no commercial
provider and makes no LLM-generated contact assertion. **Automatic official-domain
search/discovery, broad professional-directory discovery, department/direct phone
classification, and new provider onboarding are not implemented.** Existing
project-scoped person/company identities can still require reviewed association
before named contacts aggregate into a shared company. These gaps remain visible;
no speculative name join is used to mask them.

## Actual coverage

See [machine-readable local result](local-coverage.json). Scope is active,
region-eligible company identities with current customer claims, not the saved
visible-browse cohort. Unlinked projects are separately counted. Tier membership
can overlap; each denominator is distinct companies within that tier.

| Metric | Local count / denominator | Percent |
|---|---:|---:|
| Eligible companies | 0 | N/A |
| Verified work-email methods | 0 / 0 | N/A |
| Verified business-phone methods | 0 / 0 | N/A |
| Named relevant contacts | 0 / 0 | N/A |
| Generic methods only | 0 / 0 | N/A |
| Research Required | 0 / 0 | N/A |
| Lead / Prospect / Signal coverage | each 0 / 0 | N/A |

Bounded local planning scanned 0 projects with a 25-project limit. Provider requests:
0; cost: $0.00. Enrichment failure rate: N/A (0 executed attempts). These are real
local counts, **not production counts**. A production snapshot or authorized
read-only connection is needed to measure the actual TX/OK/NM baseline.

## Backfill and deployment procedure

No new migration is needed. Deploy backend and frontend from the same commit;
existing deployments must already be at migration head. Do not turn on paid
providers or broaden worker acquisition as part of this release.

1. On a staging snapshot, run existing migrations and backend/browser checks.
2. Measure and plan without writes:
   `python scripts/company_contact_recovery.py --database-target application --limit 25 --coverage`
3. After authorization for the actual database, enqueue a bounded retained-only
   page with `--apply --expected-database-name ACTUAL_DATABASE_NAME`. The default
   target is a separate `_test` database; database names are checked explicitly.
4. Save the emitted `next_cursor`, pass it as `--cursor` for the next page, and
   inspect per-job status before proceeding. Lead precedes Prospect, then Signal.
   The command's success is enqueue success, not enrichment success. Worker jobs
   retain leases, capped retries and idempotency. This route makes zero provider
   calls and cannot consume a paid-enrichment budget.
5. If priorities change during traversal, start another pass from the beginning;
   version-keyed jobs remain idempotent. Inspect unsupported/unresolved records
   instead of treating them as enriched. Resume failed jobs through the existing
   bounded retry policy; never reset attempts in a loop.
6. Recompute coverage, verify source/phone/email links after page refresh and API
   restart, and sample account identities/corrections before deployment approval.
   Production backfill and deployment remain unexecuted.

Rollback: redeploy the previous application version. No migration or deletion of
contact/evidence history is required. Previous UI will not show the new company
section; retained evidence remains available.

## Validation and independent review

- 181 relevant backend unit/PostgreSQL integration tests passed, including contact
  extraction, source dates, deadlines, account scenarios, refresh/persistence/API,
  canonical company-ID continuity and operator-retraction replay.
- Existing migrations applied on the empty local database; `alembic check` found
  no new upgrade operations. No production migration was run.
- Frontend typecheck/build passed; 12 account browser regressions passed, including
  actionable email/phone/source links after reload and at mobile size. Backend
  mypy passed across 158 source files; Ruff and diff whitespace checks passed.
- Independent reviewer identified unchecked-contact loss, false named-buyer
  counting, and account/correction continuity risks. Those findings were repaired.
  Reviewer independently ran 67 unit tests and found no remaining blocker in the
  recovery increment; full website discovery remains explicitly outside completion.

Final independent review of the current files found no remaining blocking findings
for this **draft recovery increment**. The reviewer verified v3 capture compatibility
and the separate extraction-job revision, and reviewed the legacy-success replay
and retraction tests. Production acceptance is not implied.
