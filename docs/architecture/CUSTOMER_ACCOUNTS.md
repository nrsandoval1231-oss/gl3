# Customer accounts and commercial project browsing

The [owner directive](../product/CUSTOMER_INTELLIGENCE_DIRECTIVE.md) makes a company the primary commercial browsing unit. A physical `Project` and its separate `PowerNeed` records keep their existing identities, qualification, evidence, notes, and history. A permit remains evidence. An applicant, electrician, or other contractor does not become the customer by default.

## Identity and responsibility

PostgreSQL `CompanyIdentity` remains the organization namespace. Existing current buying-chain identity links require source-bound strong identifiers or attributed review; names, employment, parent-company similarity, and shared contact strings do not merge organizations. Owner, developer, and operator responsibility must be supported independently of company identity. Contractors remain buying-chain participants.

Texas RRC memberships use the regulator's operator identifier, scoped to the two existing RRC source adapters. RRC defines the P-5 operator identifier as six digits in its [official glossary](https://webapps2.rrc.state.tx.us/EWA/help/EWA_Glossary.html) and [form instructions](https://www.rrc.texas.gov/oil-and-gas/applications-and-permits/groundwater-advisory-unit/gau-form-instructions/). The typed adapter must bind the exact operator and identifier to current retained official evidence. This supports an operator account; it does not establish purchasing authority, a temporary-power package, fuel availability, or a qualified MW gap. Diamondback E&P LLC must not silently become its corporate parent.

Versioned project memberships retain the company, physical project, participant role, original source and evidence identifiers, evidence hash, decision basis, and superseded/retracted history. Attributed corrections require an expected version and idempotency key. Automatic refresh must preserve corrections. Distinct physical sites remain distinct even when they share an operator.

## Published account summaries

Customer and unresolved-identity summaries belong to the existing `BrowseGeneration`. Maintenance validates current citations and responsibility before publication. `BrowseCustomerMembership` joins compact `BrowseRow` needs by generation and project. Ambiguous or unsupported customers remain project-specific research items rather than a combined unknown company.

Account browsing filters eligible needs on the server, groups by company UUID, counts distinct projects and needs, chooses the highest-priority matching need deterministically, and orders/pages in SQL. Total account project/need counts and counts matching the current filters are distinct. Normal reads do not scan raw evidence, acquire sources, invoke models, repair identities, or enqueue research. Account list evidence is a count; source detail remains an explicit secondary workflow.

Company search includes supported published account names and aliases as well as existing saved need text. A name/alias match selects the identity before account totals are aggregated, so a name present on only one member does not shrink the account's whole-project counts. Legacy need-level search keeps its existing semantics.

The secondary account queue materializes its matched identity set and folds support totals into the same account aggregation. Fresh-generation query plans must compute those sets once even before planner statistics recognize the newly published generation UUID; warm-only timing can conceal repeated scans.

Identity, membership, claim, correction, and evidence changes invalidate the same saved-browse revision. Incremental refresh copies unaffected account summaries with the need generation. A stale or failed refresh remains unavailable until maintenance publishes a coherent generation; it must not mix account and need revisions.

## API and UI compatibility

`GET /api/opportunities/workspace?group_by=account` provides the company queue using the existing compact workspace contract plus account identity and counts. The explicit need-level API remains available. `count_unit` identifies the result unit; account-specific cohort tokens fence pagination against changed filters, search, grouping unit, policy, or published state.

Authenticated `/api/customer-accounts`, `/api/customer-accounts/{id}/projects`, and `/api/customer-accounts/unresolved` provide bounded secondary projections. Projects and their individual needs page separately. Direct account/need links, browser history, search/filter/sort, source inspection, contacts, facts, notes, research, qualification, and operations retain their existing workflows.

Need detail exposes a nullable `associated_account` from the selected project's current accepted, unambiguous responsibility support. It includes the organization UUID, role, basis, and evidence references. This association does not establish the purchaser or alter `intelligence_card.customer`. The UI checks related account links against current detail and clears mismatched or retracted context.

The UI extends the approved [navy/white workspace](../design/UI_CANON.md). It uses company names and commercial next actions in the queue, nested projects and separate needs, and the existing intelligence card. Estimates, conflicts, unknown supply, dates, and contact authority retain their evidence status. Source documents stay collapsed until requested.

## Intelligence and authority

Existing fenced jobs, Jev contracts, grounded OpenAI research, material-change detection, cache suppression, budgets, and provider failure handling remain the execution path. No new intelligence framework is introduced. Execution receipt JSON records explicit validation outcomes and a provider response reference only when supplied. Old receipts remain `UNKNOWN`; cached results retain their original receipt. Actual cost remains unknown without a provider settlement.

This change does not authorize paid activation, select a substitute Sol model, change production credentials/data, merge, deploy, or communicate with prospects. Live Jev/Sol acceptance requires separately authorized configuration, supported model access, budgets, and genuine stored receipts. Mocked tests cannot satisfy that criterion.

## Verification and rollout boundary

Migrations `0037_customer_memberships` and `0038_customer_evidence_counts` are additive. The latter adds compact support counts and evidence dates to the account projection. Before a separately authorized rollout, preserve a recoverable database backup, apply through head, repeat the upgrade, and run `alembic check`. Application rollback must preserve memberships, retractions, original evidence, and correction history rather than downgrade/drop the new tables. The backfill CLI is restricted to an explicitly separate disposable test database in this review; a production backfill requires separate rollout authority.

The controller validates a copied retained corpus, unchanged raw-table digests, replay and history prefixes, same-name and distinct-site cases, contractor-only customers, conflicts and retractions, bounded SQL/payloads, and desktop/mobile navigation. Baseline/after p50 and p95 measurements use identical retained volume and are local database/API measurements; they are not production latency. Frozen source identity, final deterministic results, runtime captures, independent review, and blocked criteria are recorded in the PR acceptance report and local `.artifacts/customer-intelligence/` receipts. The parent [Finish Contract](../../.agent/FINISH_CONTRACT.md) remains separate.
