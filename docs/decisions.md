# Decisions

Record a date, decision, reason, alternatives considered, and affected PRD requirement when a substantive implementation choice is made. Keep product changes explicit.

| Date | Decision | Reason | Requirements |
|---|---|---|---|
| 2026-09-24 | Use new repository `gl3` and a fresh implementation. | Owner requested a clean-sheet build. | 1 |
| 2026-09-24 | Adopt the [ingestion strategy](sources/ingestion-strategy.md): prioritize validated coverage and reliable discovery; retain the managed scheduler, PostgreSQL jobs, and Python worker as the ingestion execution system. Defer n8n research workflows; consider an individual connector only with demonstrated implementation value. | Prove real source access, useful discoveries, freshness, and recovery before adding investigation infrastructure. Add historical and live discovery checks to assess coverage; document limits. Alternatives considered: n8n research orchestration first or split ingestion scheduling. | 4–12, 15–18, 35–42 |

| 2026-09-25 | Initial source selection: broad Federal Register EIS notices, then NC Commerce announcements and discovered GovInfo PDFs. | Direct public retrieval succeeded; specific development/expansion events inspected without project-name queries. PDF and JSON copies count as one underlying feed. USACE runtime 403 excludes it for now. See coverage.md. | 5, 8–13, 19, 38 |
| 2026-09-25 | Use an isolated local PostgreSQL cluster on loopback port 55439 for local proof. | Existing PostgreSQL service is preserved; Docker engine was not available. Fresh databases and generated SCRAM secret remain ignored. No cloud service or account provisioned. | 1, 3–4, 35–36 |
| 2026-09-30 | Admit standalone Signals only from official permits, project-specific official utility filings, or explicit temporary-power solicitations (`signal-admission-v1`). News supplements one supported physical project. Planning and entitlement stay research context. Deepen Chicago Express Electrical Work and Georgia Title V/SIP/synthetic-minor narrative extraction without adding a registry source. | Owner-approved GL3-018 rule, merged as PR #8 (`7f24174`). Prior evidence and claims stay retained. Standalone planning admission remains unresolved. | 5, 14, 17–21, 26, 42 |
| 2026-09-30 | Generate the CI database password, session secret, and app password hash on the runner. Do not commit those values. | They configure only the ephemeral CI Postgres service and tests. They are not deployed credentials. Copies already in git history remain exposed. | 35 |

| 2026-10-01 | Select RRC monthly products by America/Chicago calendar date and scope runtime recovery to explicit job IDs. | Live recovery at UTC month rollover requested an unpublished September EOM while Texas was still in September. Publisher-local dates fix selection without relaxing freshness; scoped leasing preserves unrelated backlog and normal retry backoff. | 5, 10–11, 36–37 |
| 2026-10-01 | Preserve a currently supported admission citation during unchanged grouped-permit replay. | Live strict replay found three Austin phase permits swapping the saved basis and updating the opportunity timestamp. Validate the saved basis against current evidence/interpretation/project/activity/policy before retaining it; repair invalid bases. | 10–11, 17, 32, 37 |

## October 1, 2026 — Priority geographies, activities and flare permits

Owner requests Dallas, Austin, Houston, El Paso and California first; data-center construction, data-center commissioning and oil and gas in that commercial order. Keep other national/industry intake wide. Add reproducible official flare-gas permits/venting-flaring exceptions to ingestion with source-specific event semantics and UNKNOWN gas-to-power fit. This changes acquisition priorities, not qualification gates or the 300 kW/no-maximum presentation amendment.


## October 1, 2026 — Evidence graph ingestion and Jev judgment layer

GridLens is a project-reconstruction and commercial timing engine, not a generic lead scraper. Canonical flow: source evidence -> immutable capture -> parse/normalize -> deterministic matching -> bounded Jev judgment where ambiguity remains -> canonical project/entity graph -> change detection -> selective enrichment -> Signal -> Prospect -> Lead -> actionable pursuit.

Adopt the architecture in [Evidence Graph and Jev Judgment Architecture](architecture/evidence-graph-jev.md). Preserve current collectors, admission rules, deterministic promotion gates, and Signal/Prospect/Lead semantics during migration. Code owns facts, hard rules, math, state and writes. Jev is a fast bounded judgment layer for relevance, ambiguous entity adjudication, event classification, change significance, power relevance and enrichment escalation. Deep generative models are reserved for complex synthesis/research.

First Jev slice is a feature-flagged `EvidenceJudge` in shadow mode. It has no initial authority to mutate canonical truth or promotion outcomes. Measure precision, false positives/negatives, latency, cost, invalid/timeout behavior and escalation yield on labeled existing evidence before expanding authority. Failure falls back to existing deterministic behavior. Do not add a general Jev framework or another orchestration layer.


## October 4, 2026 — Bounded autonomous pursuit questions (candidate)

Reuse PostgreSQL Job targets and fencing, canonical ingestion, conservative exact
project matching, buying-chain provenance, and the commercial evaluator. Add one
question table because existing brief caching cannot represent two separately
bounded blockers with histories and retry windows. Keep acquisition and evidence
admission separate; a search result is never canonical evidence. Reserve request
budgets before I/O and persist uncertain completion instead of retrying paid requests
blindly. Reevaluate through the shared deterministic service, never worker-assigned
pursuit states. Reject a general orchestration framework and new persistence layer.
This implements the GL3-029 objective without changing Signal/Prospect/Lead gates.
Local fixtures now cover commercial transitions and positive Prospect/Lead gates;
required original retained-corpus proof remains blocked. Typed public reports are
independent source-attributed facts, never positive qualification authority. Add a
narrow official-permit implementation of existing PRD criteria rather than inventing
a research-worker promotion path. Keep conflicts and dated corrections explicit.
Hourly saved-target projection avoids shortlist starvation; immutable evaluation
versions drive morning metrics. No new model or orchestration framework is added.

### Same-candidate review repairs

Keep blocking DNS, HTTP and parsing inside killable acquisition-only child processes
under the existing question deadline and 512 MiB address-space cap. Budget reservation,
lease ownership and all database writes remain in the parent worker; this is a bounded
I/O boundary, not another orchestration system. Reject whole oversized/incomplete
public inputs rather than extracting a prefix that might omit contradictory text.
Allow separately budgeted rendering only for successful explicit public JavaScript
shells; access restrictions never justify a fallback.

Reuse six stable native GET routes and proven-complete retained public inputs with
original evidence identity. Exact validated registry hosts can support supplements,
not inherit native-source qualification authority. Record partial progress only for
the question actually asked. Accept explicitly supported aggregate nonzero suitable
supply over the full activity interval, calculate conservative residual bounds, and
apply the Lead commercial floor to remaining need. No suitability, component totals,
project assignments or buying authority are inferred. Final repaired-candidate gates
and original retained-corpus proof remain distinct from these implementation decisions.

## October 7, 2026 — fresh corpus regeneration authorization

The owner directed recreation of missing corpus/R4 artifacts, superseding original archive recovery. Preserve historical results; label all new records and receipts `reingested` with acquisition UTC, source identity, hashes, candidate and database provenance. Do not alter the original retained-proof branch or five-cohort predicate. An explicitly partial diagnostic reuses existing canonical case checks, bounded execution, preservation and replay while forcing full and retained acceptance false. Unsupported O&G candidates remain ineligible.

The regeneration wrapper uses existing native permit adapters and PostgreSQL jobs/admission. Federal Register is excluded from this wrapper because its ingestion can implicitly retrieve companion PDFs outside the collection budget. Full-table row inventories verify isolated backup/restore. No general orchestration, source authority expansion, paid provider enablement, outreach or deployment is introduced.

### October 7 — prevent avoidable stale siblings at planning

The first regenerated run demonstrated two obsolete queued siblings after retained
buying-chain derivation. Preserve those failed receipts and the worker freshness
check. Derive already-retained relationships before freezing new question contexts,
then use the existing deterministic evaluator. Exclude active projects and serialize
project locks in stable order. New corpus validation must prove both siblings finish
on unchanged native evidence and real post-queue changes still stop before I/O.
Drilling remains eligible for early O&G Signals under the existing RRC admission
policy; the initial fixed-infrastructure-only scout was too narrow and is not proof
that the existing drilling route lacks eligible records.

### October 7 — bounded inspection of complete retained RRC records

After explicit owner authorization, the existing anonymous RRC public-download form
retrieved real daily/monthly files for fresh corpus regeneration. Exactly one selected
approved drilling record entered the existing canonical pipeline. Autonomous research
may inspect its complete retained native bytes through the existing parser/renderer,
strict bounded reconstruction and accepted exact identity checks. This is Tier A
inspection with original acquisition timestamps, not a new network adapter or a
claim of exhaustive public research. Opaque child records remain uninterpreted and
permit approval does not establish current drilling, temporary demand or buying power.

Keep the existing validator and finite provider-unavailable retry behavior unchanged.
All five regenerated categories now pass mechanical investigation/preservation/replay;
six blockers remain unresolved, with no promotion. Historical original-corpus proof
and unavailable historical browser prerequisites are not substituted. Canonical docs
link the final exact-candidate report; older failure/authorization receipts remain
immutable history. No new architecture, migration, outreach or deployment follows.

## October 7, 2026 — complete local acceptance and bounded TDLR retrieval

The owner authorized the existing public TDLR search form solely for retrieval after the original no-forms boundary was explained (message Sentinel_e58b307f03488191abf3194a12196ad4, 04:30:46 UTC). This permits rebuilding real legacy pursuit/conflict history and conditional merge; it does not authorize outreach, login, purchases, credentials or deployment.

Keep canonical admission unchanged. A proven Georgia false negative was corrected by normalizing the legal term Company, retaining exact station/city checks. Rejected corpus candidates stayed rejected; genuine additional manufacturing permits supplied history pagination, with same-address phases retaining separate stable identities. All 42 browser tests and 1,232 backend tests pass (one optional skip); final fresh five-category acceptance is 5/5 with honest unresolved results. Positive autonomous new-fact resolution is not claimed. See [final evidence](validation/gl3-029-final-acceptance-20261007.md).

## October 13, 2026 — repository names and ownership notes

The PRD tree names `Dockerfile.api`, `Dockerfile.worker`, `scheduler.yaml`, a root `Makefile`, and `config/sources/*.yaml`. The repository uses `deploy/Dockerfile.backend`, `deploy/Dockerfile.web`, `deploy/scheduler.preparation.yaml`, `scripts/check.ps1`, and `config/sources/registry.v1.json`. These are names for the same preparation and check roles. They do not add a scheduler, a deployment, or a source.

Folder README files stay where a milestone names a module that is not implemented yet. They record ownership. They do not mean the named capability exists. Empty-directory READMEs are not deliverables.

The registry has no separate parser field. Adapter selection is `retrieval_method` in `ingestion/adapters/__init__.py`. Requirement 5's parser attribute is that method, not a second id.

## October 14, 2026 — owner decisions for deployment (Phase 0)

Nick decided:

- **Hosting:** DigitalOcean for compute, managed PostgreSQL and backups; Cloudflare for DNS, TLS and edge access in front of the app.
- **Source artifacts:** DigitalOcean Spaces (S3-compatible) for permitted documents and snapshots. Resolves audit D4.
- **Owner alerts:** ntfy push to Nick's phone for overdue daily collection and material processing failures. Resolves the channel choice in audit D3; the sender is still to be built.
- **AI provider:** fold all model calls into one provider adapter. The shadow evidence-judge client is to be removed or routed through that adapter. Resolves audit D5 direction; the provider is OpenAI.
- **First Lead path:** Nick will make 3–5 discovery calls on the strongest current Signals. Facts he confirms enter as attributed User-confirmed evidence (Requirement 30); they do not bypass the Lead gate.

The build sequence is in [delivery/build-plan.md](delivery/build-plan.md).

## October 14, 2026 — records that leave a complete source listing

Sources whose adapter returns every listed row or fails may set `snapshot_complete` in the registry (allowed for `georgia-air-permits` and `tceq-nsr-pending`). After each successful run of such a source, a stored record missing from the listing gets a dated `absent_from_source` change event, and `returned_to_source` if it reappears. Evidence, interpretations and needs are not deleted or closed: leaving a pending listing can mean issued, denied or withdrawn. The need is shown with a status-review flag (`signal_evidence_state: source_listing_absent`) and a status-review next action. Rolling-window city permit feeds do not opt in, because aging out of a window is not a status change.

## Owner decision October 20 2026: site-specific news may create discovery Signals

Owner decision received October 20, 2026, in the current task conversation:

> “Allow site-specific news to create standalone discovery Signals, with unknown power facts and the existing Prospect/Lead gates.”

This supersedes the September 30 row above only for site-specific news Signal admission. Preserve that row and its historical context. A discovery Signal may exist without an established temporary-power need or a supported power gap. Unknown power facts remain unknown: do not infer temporary MW, duration, buyer identity, or buying authority from a site announcement. The existing evidence-based Prospect and Lead gates remain unchanged. No source-specific final rule, source activation, qualification change, or implementation acceptance is recorded here; the implementation handoff and validation are pending. The PRD and UI canon are unchanged.
