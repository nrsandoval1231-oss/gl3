# Autonomous commercial research Phase 2 — November 8, 2026

## Authorized scope and delivery

Owner authorizes full local implementation and verification through one independently reviewed draft PR, based on `bc433650ce4706dddfb5b30d78a502e3b528f54e` (merged PR187). No merge, deployment, mutations of retained operational or production data, credential changes, paid provider calls or source activation. All tests use new disposable databases and disabled providers. Writing retained evidence and findings into those new disposable databases is required acceptance work; existing operational/retained datasets are never test targets. Dated receipts remain historical.

## Contracts and ownership

Reuse the current durable jobs, fenced leases, planner state, evidence packages, public acquisition, provider ledger, source admission and canonical account projections. No second orchestration engine. A company research pass is keyed by canonical company and supported input versions; distinct physical projects and needs remain distinct. Refresh is justified by material evidence changes, actionable missing facts or expiry; volume alone is not utility. Failures preserve last accepted facts and explicit internal limitations.

The commercial projection adds an optional `commercial_brief` object to existing workspace need payloads: `version`, `why_now`, `power_need`, `best_contact`, `next_action`, `freshness`, `limitations`, `sources`. Claims include supported source/event date and scope when available. `power_need` keeps amount class and scope explicit; unknown is not zero; campus/nameplate/IT amount never becomes rental demand. `best_contact` uses existing privacy-filtered permitted contact actions, with generic/direct and authority/deliverability unknown retained. Browser routes remain read-only and never call providers. Sources stays collapsed; header, four tabs, palette, fonts and responsive/history/session behavior remain.

Contact authorization contract: a current native contact fact binds canonical company ID, normalized method kind and literal value, exact person scope (including an exact unnamed scope), role/title/support/authority semantics, and the current native source URL and version hash. A supported quote or matching URL alone cannot authorize a different method. Fresh and cached public projections use the same matcher. Cached records must match a regenerated current authorized record's complete public semantics, including name, title, role and responsibility; source-version uncertainty abstains. Existing parsers and retained provenance provide these facts. An imported website/domain hint, self-declared identifier or generic project-research relevance is not independent employer/domain authority. The current producers do not supply an authoritative website-domain binding, so website acquisition can run while unverified website contact publication remains blocked.

| Lane | Exclusive implementation ownership | Interface |
|---|---|---|
| A acquisition/planning | autonomous_research.py, pursuit_questions.py, research_routing.py, ingestion/adapters/pursuit_acquisition.py and their focused tests | Existing question/job APIs, source/ledger controls; no settings/models/worker writes |
| B commercial interpretation | new domain/commercial_brief.py, project_results.py, commercial_evaluation.py, customer_accounts.py, pursuit_workspace.py and focused tests | `build_commercial_brief(item: dict, *, now=None) -> dict`; existing payload plus optional brief |
| C public/optional contacts | company_contact_discovery.py, company_contacts.py, enrichment_planner.py, optional Apollo adapter, public_site_policy.py, buying_chain_public.py, budgeted buying_chain.py callsites/contact projection, company_contact_attribution.py, any explicitly leased project_contact_actions.py read guard and focused tests | Existing company jobs and contact persistence; Apollo disabled/activation blocked unless separately authorized |
| D product | web source/client types and browser tests, except generated API artifacts | Render optional brief; preserve old payload fallback and privacy cleanup; add fixture acceptance |
| E acceptance | new scripts/phase2* and backend/tests/integration/test_phase2_acceptance.py in the primary worktree | Real persisted worker-to-projection fixture and same-fixture baseline/candidate receipts |
| Coordinator | worker/settings/API/models/generated artifacts/integration and maintained docs | Lease shared files explicitly; integrate and run final gates |

Implementation builders A–D initially use separate managed worktrees from the same base; builder E owns acceptance files in the primary worktree. Explicit exclusive primary-file leases later covered D's CI/legacy-test fixtures, C's annotation-only mode repair, B's serializer/privacy repair, and A's additional native privacy/readiness fixtures. These exceptions did not share concurrent file writers. Shared-file leases above were extended explicitly as integration needs became concrete. The lead integrates commits sequentially. Five exact Luna/low builders (four implementation lanes and one cross-lane acceptance lane) were dispatched; independent Astra/high scoped review and difficult-root-cause escalation have run. Final integrated review remains required. Root handles owner updates and bounded verification assistance.

## Acceptance and next steps

1. Audit/finish bounded existing scheduling/acquisition and disabled-mode end-to-end path; deterministic provider fixtures cover errors, replay, limits and recovery.
2. Ground concise commercial brief in accepted source versions; no guessed amounts/dates/buying authority. Preserve identity/privacy and last good facts.
3. Finish public contact workflow; optional Apollo interface with official-doc evidence and explicit activation block where license/access unavailable.
4. Integrate compact UI without new tabs or machinery. Real disposable PostgreSQL worker-to-card journey, adversarial identity/power/contact/privacy/provider cases and same-fixture baseline/candidate metrics.
5. Full local gates, five viewport browser evidence, exact-head independent review and full CI; publish one draft PR, never merge/deploy.

Metrics distinguish synthetic fixtures from retained/production coverage, and mock provider dollars from unknown actual cost. No authorized sanitized retained snapshot has been identified yet; prior production replay is not reused as fresh evidence.

## Runtime and rollback boundary

This candidate does not authorize runtime activation. No schema migration is planned; exact final source and migration checks must confirm that at handoff. Existing immutable evidence, company/project identity, saved Pursuits and provider ledgers remain in place. Application rollback retains forward schema and history; stop/reconcile fenced in-flight jobs using the existing recovery procedure before any separately authorized worker version change. Do not downgrade/delete evidence or restore old data as an automatic rollback action.

Optional public-page automation now requires exact-host dated terms permission in addition to public-network and robots checks. No actual approved hosts are shipped. Unknown permission is an internal blocked outcome, preserving retained/native results. Metadata-only Firecrawl search is distinct from remote HTML extraction; post-fetch URL checks do not prove remote redirect prevention. Where provider target-network capability cannot be evidenced, live extraction stays blocked, with only deterministic parser/contract fixtures exercised. Apollo access, licensing, entitlement and live connector remain unavailable; its disabled interface does not imply vendor activation or usable contacts.

## Current acceptance state

Production and the metrics harness are frozen after the A recovery/grouped-worker repairs and the cohesive C private-evidence/public-publication repair at `ffc3c890`. Independent scoped reviews closed those concrete findings; the [current checkpoint](../../.agent/CURRENT_STATE.md) records the repair sequence and remaining checks. The [validation record](../validation/autonomous-commercial-research-20261108/README.md) includes an accepted same-fixture pair on those source hashes and distinguishes it from final integrated acceptance. Failed fixture attempts remain failures. Final fixture verification, the fresh viewport journey, independent exact-head review, broad gates and exact-head CI remain required before the draft PR handoff.

## Optional provider capability boundary

Apollo is an always-blocked, no-network interface (`apollo_contacts.py`); it is not a working licensed connector or an environment flag that activates one. Account access, licensing, endpoint entitlement, credits, price and permitted use remain unverified. A future activation requires a separately reviewed governed implementation that supplies authorization, bounded spend accounting, identity/employer matching, response validation and recovery before any live smoke; changing a module constant is not an activation procedure.

Firecrawl metadata-only search and HTML extraction are distinct capabilities. Search's current contract is fixture-tested without target-page scraping; no live/paid result is claimed. Remote HTML extraction remains capability-blocked where target redirect/private-network guarantees cannot be established. The provider/source permission and robots guards do not turn a post-fetch URL check into prevention of remote target redirects.
