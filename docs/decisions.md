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
