# Autonomous commercial research Phase 2 — November 8, 2026

## Authorized scope and delivery

Owner authorizes full local implementation and verification through one independently reviewed draft PR, based on `bc433650ce4706dddfb5b30d78a502e3b528f54e` (merged PR187). No merge, deployment, retained/production writes, credential changes, paid provider calls or source activation. All tests use new disposable databases and disabled providers. Dated receipts remain historical.

## Contracts and ownership

Reuse the current durable jobs, fenced leases, planner state, evidence packages, public acquisition, provider ledger, source admission and canonical account projections. No second orchestration engine. A company research pass is keyed by canonical company and supported input versions; distinct physical projects and needs remain distinct. Refresh is justified by material evidence changes, actionable missing facts or expiry; volume alone is not utility. Failures preserve last accepted facts and explicit internal limitations.

The commercial projection adds an optional `commercial_brief` object to existing workspace need payloads: `version`, `why_now`, `power_need`, `best_contact`, `next_action`, `freshness`, `limitations`, `sources`. Claims include supported source/event date and scope when available. `power_need` keeps amount class and scope explicit; unknown is not zero; campus/nameplate/IT amount never becomes rental demand. `best_contact` uses existing privacy-filtered permitted contact actions, with generic/direct and authority/deliverability unknown retained. Browser routes remain read-only and never call providers. Sources stays collapsed; header, four tabs, palette, fonts and responsive/history/session behavior remain.

| Lane | Exclusive implementation ownership | Interface |
|---|---|---|
| A acquisition/planning | autonomous_research.py, pursuit_questions.py, research_routing.py, ingestion/adapters/pursuit_acquisition.py and their focused tests | Existing question/job APIs, source/ledger controls; no settings/models/worker writes |
| B commercial interpretation | new domain/commercial_brief.py, project_results.py, commercial_evaluation.py and focused tests | `build_commercial_brief(item: dict, *, now=None) -> dict`; existing payload plus optional brief |
| C public/optional contacts | company_contact_discovery.py, company_contacts.py, enrichment_planner.py, optional Apollo adapter and focused tests | Existing company jobs and contact persistence; Apollo disabled/activation blocked unless separately authorized |
| D product | web source/client types and browser tests, except generated API artifacts | Render optional brief; preserve old payload fallback and privacy cleanup; add fixture acceptance |
| E acceptance | new scripts/phase2* and backend/tests/integration/test_phase2_acceptance.py in the primary worktree | Real persisted worker-to-projection fixture and same-fixture baseline/candidate receipts |
| Coordinator | worker/settings/API/models/generated artifacts/integration and maintained docs | Lease shared files explicitly; integrate and run final gates |

Builders use separate managed worktrees from the same base and commit only owned files. The lead integrates commits sequentially. Five exact Luna/low builders (four implementation lanes and one cross-lane acceptance lane) and independent Astra/high final review are required and supported by runtime metadata. Root handles owner updates and bounded verification assistance.

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
