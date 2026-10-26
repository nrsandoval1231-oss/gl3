# GridLens — Jev + LLM Intelligence Integration Strategy

> Historical integration strategy. Preserve compatible evidence/model safeguards; pursuit statuses, manual workflow and previous harness directions are superseded. Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md).


**Status:** Proposed implementation strategy; subordinate to existing GL3 canonical PRD, approved evidence architecture, security boundaries and owner decisions
**Prepared:** October 18, 2026
**Repository:** [`nrsandoval1231-oss/gl3`](https://github.com/nrsandoval1231-oss/gl3)
**Suggested repo destination:** `docs/architecture/INTELLIGENCE_INTEGRATION_STRATEGY.md`
**Decision owner:** GridLens product owner

> **Executive decision:** GridLens should be an evidence-governed commercial timing engine, not an LLM-powered lead scraper. Use deterministic software to acquire and preserve facts; **Jev to make bounded categorical judgments about ambiguity, relevance and research allocation**; fast structured-extraction LLMs to recover source-attributed facts from difficult documents; and **OpenAI reasoning models** for selective deep research, reconciliation and commercial synthesis. No model independently admits a Lead, merges uncertain entities, fabricates MW or timing, or authorizes outreach.

## 1. Goal and non-negotiable business outcome

GridLens must answer: **Which identifiable physical projects will require temporary, commissioning, bridge, or behind-the-meter power; when, at what defensible MW/duration, why might permanent supply be insufficient, and who can authorize or influence procurement?**

Success is **more timely, evidence-backed direct-buyer opportunities**, not more ingested documents, model calls, automatically generated narratives, or arbitrary signal counts.

- Prioritize **data-center construction**, **data-center commissioning**, and **oil-and-gas power**, while keeping nationwide, cross-industry ingestion. Give acquisition preference to Dallas, Austin, Houston, El Paso, and California, without misrepresenting actual coverage.
- Retain separate **Project**, **power activity/need**, **commercial tier**, **priority**, and **pursuit status**. A 200 MW campus is not a 200 MW temporary rental opportunity.
- Preserve the established **Signal → Prospect → Lead** qualification ladder. Keep the **300 kW inclusive visible opportunity floor**; unknown-size Signals can remain visible as unknown. Never promote a record because an LLM sounds confident.
- Prefer end users and authorized buying-chain participants; do **not** recommend re-renters as direct prospects. Contractor, applicant, owner, developer, utility, and actual buyer roles are distinct.
- Every user-facing consequential claim must have evidence references, source dates, review status and a clear *unknown/conflict* state. An absence of utility information is **not** proof of a power shortage.
- Preserve PC-off operation as an acceptance requirement, not a presumed current capability.

## 2. Repository baseline: verified architecture versus proposed extension

**Verified from the GitHub repository as reviewed on October 18, 2026:**

- GL3 uses **FastAPI backend + separate Python worker + React/TypeScript frontend + PostgreSQL** with durable job architecture. See [`docs/architecture/overview.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/architecture/overview.md).
- An approved October 1 canonical design already specifies **immutable Observation/Evidence versions → normalization → deterministic matching → bounded Jev → project/entity graph → change detection → selective enrichment → Signal/Prospect/Lead → pursuit**. See [`docs/architecture/evidence-graph-jev.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/architecture/evidence-graph-jev.md).
- **EvidenceJudge shadow** and a separate pre-existing Jev signal-adjudication path are documented. EvidenceJudge's categorical results are advisory, stored independently, and do not enqueue research or mutate authoritative facts. Defaults prevent provider calls in routine ingestion; a **durable PENDING reservation** addresses interrupted calls. See [`docs/validation/gl3-028-evidence-graph-jev-shadow.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/validation/gl3-028-evidence-graph-jev-shadow.md).
- Existing permit and buying-chain enrichment already distinguishes project, company, person and authority; it must be reused, not replaced. See [`docs/sources/gl3-019-permit-enrichment.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/sources/gl3-019-permit-enrichment.md).
- At review, [`docs/delivery/milestones.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/delivery/milestones.md) identified **unproven PC-off scheduled cycles, alerting, restore drill, broad live coverage, and an independently discovered real Lead**. The newer `.agent/CURRENT_STATE.md` also explicitly reports **live collection/research/Jev/shadow/scheduling OFF with zero budgets**. A public app URL or passing test suite does not override those recorded runtime restrictions. Current live status must be rechecked before enablement.
- The owner authorized **removal of the editorial workflow** on October 18. **Do not reintroduce editorial assessment, newsletter dependencies, publishing or exports** as part of this integration.

**This document proposes** a unified intelligence control plane *within the existing app and worker*, evaluation and rollout contracts, and several additional routing/LLM functions. These are **not claims of already-deployed features**. The current implementation and API surface must be inspected at exact commit before a builder edits code. The PRD remains authoritative in any conflict.

## 3. Clear model responsibility matrix

| Actor | Owns | Allowed output | Explicitly forbidden |
|---|---|---|---|
| **Deterministic Python/domain services (authority layer)** | Fetch, hash, checksum, parse structured sources, identities/exact IDs, dedup, provenance, immutable versions, dates/math, candidate selection, graph diff, tier gates, priority business rules, job leases, policy and writes | Verified typed facts, immutable evidence, approved state transitions, auditable calculation | Inference beyond evidence; auto-accepting speculative model claims |
| **Jev (System One decision layer)** | **Fast, bounded categorical/ordinal judgment on ambiguous evidence**: relevance, intent, candidate match, event class, materiality, power-use-case hints, importance of research, route recommendation | Enumerated `choice`, ordinal `score`, `noul`/yes propensity where compatible with pinned API contract; immutable advisory decision record | Open-ended prose generation, factual research, fetching, code execution, arithmetic, canonical writes, Lead promotion, autonomous identity merges, assigning calibrated business probabilities |
| **Fast extraction LLM (configured provider; OpenAI small/fast model as default)** | Recover named entities, locations, quote-grounded dates, MW figures, equipment, project stage, relationships and passages from complex prose/PDF/OCR | Structured claim candidates **with exact evidence spans and units** | Declaring claims verified; inventing unknown values; making final tier decisions |
| **OpenAI reasoning/research model (deep investigator)** | Cross-source reconciliation, ambiguous project reconstruction, power-need hypothesis formation, targeted research plans, locating buying-chain evidence, conflict explanations, sourced brief synthesis | Structured research findings, cited hypotheses, missing-evidence list, proposed next-source queries, human-readable brief | Unfenced browsing, inventing current data, bypassing authorization, unilateral accepted facts or external actions |
| **Optional secondary model (independent reviewer, provider-agnostic)** | On selected high-impact disagreements, independently check citation-to-claim fidelity, detect omitted contradictions, challenge unjustified power assumptions | Review flags, disagreement summaries, citations | Acting as a second vote that makes false claims true; serving as an automatic Lead approval |
| **Human commercial owner** | Verify buyer feedback, set pursuit priority, approve contact decisions, correct facts with attribution | Owner notes/confirmations, authorized pursuit actions | Untraceable retroactive alteration of source evidence |

**Preferred simple initial stack:** existing Python rules + existing Jev TypeSafe adapter + **one** OpenAI fast structured-extraction/research interface + **one** OpenAI stronger reasoning configuration for difficult cases. Do not add three generic autonomous agent frameworks or multiple model vendors before evidence shows a need. Pin actual provider and model IDs in versioned config after checking current supported models, rather than hardcoding unverified SKU names here.

## 4. Jev's exact role in GridLens

### 4.1 Good Jev calls (proposed decision catalog)

Each call occurs **after cheap deterministic filtering** and uses bounded source text or structured facts, accepted graph state and candidate identity list. Reuse existing Jev paths; deduplicate overlapping judgments instead of building parallel pipelines.

| Decision ID | Business question | Output type | Trigger | Effect allowed after promotion |
|---|---|---|---|---|
| `SOURCE_RELEVANCE_V1` | Is this evidence potentially useful for a physical project or a power need? | Choice `RELEVANT/IRRELEVANT/UNCERTAIN` | New ambiguous retained item; no obvious deterministic decision | Queue review/targeted parse; do not discard evidence |
| `EVENT_CLASS_V1` | What kind of project event is shown? | Enum e.g. formation, construction, energization, commissioning, procurement, other, unknown | New text event not source-typed conclusively | Advisory event label; evidence acceptance remains separate |
| `MATCH_ADVISORY_V1` | Is evidence about *this* candidate physical project? | Choice `SAME/DIFFERENT/UNRESOLVED` **per deterministic candidate** | Narrow ambiguous candidate set | Recommend linking for validation; **never automatically merge high-risk identity** |
| `MATERIALITY_V1` | Does the **content** suggest a meaningful commercial change? | Choice `MATERIAL/ROUTINE/UNKNOWN` | Actual version or accepted-state change | Assist review/routing, never rewrite deterministic graph diff |
| `POWER_ACTIVITY_HINT_V1` | Which power-need use case could this source concern? | Choice construction, commissioning, bridge, BTM, oil-gas, other, unknown | A source with power context but unclear activity | Route next research; **hint is not an established requirement** |
| `RESEARCH_PRIORITY_V1` | Does the marginal expected business value justify deeper research now? | Ordinal 1–5 or fixed categories | Evidence delta with unresolved questions and budget | Candidate for **deterministically budgeted** enrichment queue |
| `BUYER_ROLE_HINT_V1` | What relationship does the mentioned party likely have? | Enum owner, developer, GC/EPC, engineer, utility, vendor, unknown | Ambiguous role references | Candidate relation pending source verification, never proof of authority |
| `LLM_ROUTE_V1` | Which bounded processing tier is warranted? | Enum `NONE/FAST_EXTRACT/DEEP_RESEARCH/HUMAN_REVIEW` | Cost-sensitive ambiguity not resolved by rules | Advisory routing subject to limits and policy |

**Caution:** Do not pack all decisions into one unbounded mega-request. Batch related questions over a shared compact context only when the actual TypeSafe Jev API and latency profile support it. Separate identity from commercial routing when differing audit and recall policies matter.

### 4.2 Jev is NOT the lead qualification score

- `noul` is a model's yes-type output, **not** automatically a validated real-world probability of temporary-power demand, procurement or winning a deal.
- Jev ordinal scores are ranking features; **not** MW estimates, expected duration, confidence intervals, dollar values or commercial-close probabilities.
- Current GL3 deterministic admission thresholds remain the authority. Relevance **false negatives** are particularly dangerous: uncertain items remain searchable and/or reviewed, not silently dropped.
- Jev never overrides a source's permitted use, retention, withdrawal, or official document state.

### 4.3 Canonical Jev decision record

Use existing tables and contracts where possible; the following is the **logical** record, not an instruction to create redundant tables:

```json
{
  "decision_id": "uuid",
  "decision_contract": "RESEARCH_PRIORITY_V1",
  "observation_id": "uuid",
  "evidence_version_id": "uuid",
  "project_id": "uuid-or-null",
  "power_need_id": "uuid-or-null",
  "context_digest_sha256": "sha256-hex",
  "prompt_contract_version": "v1",
  "provider": "typesafe",
  "model_id": "pinned-deployed-model",
  "raw_output_ref": "restricted-reference-if-retained",
  "normalized_result": {"choice": "DEEP_RESEARCH", "score": 4},
  "validation": "VALID",
  "policy_action": "ADVISORY_ONLY",
  "status": "COMPLETED",
  "input_token_count": null,
  "latency_ms": null,
  "estimated_cost_usd": null,
  "created_at": "ISO-8601"
}
```

Populate measured values only; `null` means **unknown/not reported**, not zero. Validate model JSON/choices strictly against the currently pinned official TypeSafe contract; avoid combining hypothetical result keys into a single provider request before verifying its actual schema. Store source references, not entire sensitive payloads in logs.

### 4.4 Jev authority progression

1. **Disabled (current safety posture)** — no provider calls, no spending; validate key handling and current live controls.
2. **Explicit shadow evaluation** — replay labeled evidence with an authorized bounded budget; no user-facing admission or research scheduling influence.
3. **Advisory UI** — visible suggested research/classification with evidence and provenance; no automatic graph or tier writes.
4. **Bounded routing** — allow **only** verified `RESEARCH_PRIORITY`/`LLM_ROUTE` decisions to recommend job scheduling, mediated by deterministic token/$/quota policy and source restrictions.
5. **Optional later** — limited low-risk classification authority only after independently assessed per-class recall and business impact. **Never** automatically merge uncertain projects or promote Lead based solely on Jev.

## 5. End-to-end production architecture

```text
PUBLIC/OFFICIAL SOURCES                  OWNER-ATTRIBUTED INPUTS
  |                                      |
  +-------------+------------------------+
                v
     SOURCE REGISTRY + SCHEDULER
       (frequency, legal limits,
        fetch budget, priority)
                |
                v
       ACQUIRE / CHECKPOINT / RETRY
       (APIs, RSS, docs, portals)
                |
                v
     IMMUTABLE OBSERVATION + EVIDENCE
       (hash, dates, page, origin)
                |
                v
      DETERMINISTIC CHANGE + PARSE
       (no-change short circuit,
        structured source extraction)
                |
           [hard document?]
                | yes
                v
      FAST STRUCTURED-EXTRACTION LLM
      -> grounded candidate claims
                |
                v
         VALIDATE / NORMALIZE
     (units, spans, conflicts, unknown)
                |
                v
      DETERMINISTIC IDENTITY CANDIDATES
                |
          [ambiguity remains?]
                | yes
                v
      JEV BOUNDED JUDGMENT (ADVISORY)
                |
                v
     PROJECT + POWER-NEED EVIDENCE STATE
                |
                v
     DETERMINISTIC GRAPH DIFF / GATES
                |
                v
     JEV RESEARCH-PRIORITY ADVISORY
                |
        POLICY/BUDGET ROUTER
           /           \
          v             v
      MONITOR       DEEP OPENAI RESEARCH
                   (targeted retrieval,
                    buyer/power gap)
                         |
                         v
                VALIDATE AND RECONCILE
                 source-backed claims
                         |
                         v
          DOMAIN POWER-GAP CALCULATIONS
          + SIGNAL / PROSPECT / LEAD
                |
                v
        ACTIONABLE OPPORTUNITY VIEW
        (delta, MW, time, gaps, buyer,
         next action, unknowns, sources)
                |
                v
        OWNER FEEDBACK + OUTCOMES
             -> evaluation corpus
```

**Control-plane rule:** The existing PostgreSQL-backed jobs, worker, and API remain the execution substrate. Model calls are bounded **jobs**, not new unsupervised agents. There is no requirement to adopt a graph database, Kafka, a vector database, a new queue, or an agent framework.

## 6. Persistent ingestion: two loops, one source of truth

### 6.1 Broad discovery

- Registry of authorized and enabled sources with purpose, region, asset/lifecycle stage, cadence, parser version, access/retention restrictions, expected freshness and last-success metadata.
- Incremental fetch using source cursors/ETags/last-modified when supported; content hash and source identity drive idempotency.
- No-change **skips all LLM/Jev work**; preserve check metadata without creating false project changes.
- Structured APIs, official filings, planning and utility dockets first; news is corroborating and exploratory, never automatically dispositive.
- A valid HTTP response containing malformed or empty-unexpected content is a **visible parse/source failure**, not a success.
- Rate-limit by source, bounded concurrency per host, global request capacity, request timeout, retry backoff/jitter, quarantine for repeated parser errors.
- Store raw content only where permitted; preserve source URL, immutable hash and minimally sufficient excerpts otherwise.

### 6.2 Targeted monitoring

- When a canonical Project or power activity is accepted, build an **evidence-source watch set** linked to unresolved questions: energization timing, upcoming construction, temporary permits, procurement, contractor attribution.
- Revisit sources more frequently only when justified by stage and expected change cadence; keep national discovery running independently.
- New material evidence or accepted version withdrawal triggers deterministic reassessment. Failed retrieval **must not erase** previously supported facts; show staleness separately.
- Use budget and lifecycle-driven prioritization, not uniform LLM passes across every item.

### 6.3 Job state and reliability

Every job has `queued/running/succeeded/partial/retryable_failed/permanent_failed` semantics (map to existing status values), explicit attempt count, deadline, cost reservation, idempotency key, worker lease and fencing token. On crash/restart, do not double-spend unintentionally or duplicate persistent claims. Maintain a dead-letter investigation surface and last-good canonical state. Avoid cron inside a developer workstation; schedule cloud execution with explicit owner authorization and proof.

## 7. The enrichment layer, explicitly separated

**Enrichment is not just a search call.** It is a question-driven process that turns a specific missing commercial fact into a cited answer, accepted conflict, or explicit unknown.

### 7.1 Enrichment objectives

For each distinct project **power activity**, prioritize:

1. **Physical identity and stage:** site, developer/owner, actual activity, milestone and timing.
2. **Demand:** evidence for *activity-specific* power MW/range and duty (construction vs commissioning vs operations), load basis and unit conversions.
3. **Available supply:** utility service evidence, existing onsite power and constraints, timing of energization or interconnection.
4. **Gap:** compute supported remaining MW/time gap via versioned deterministic domain code; never infer shortage from general market headlines.
5. **Delivery feasibility:** temporary generation fit, voltage, fuel type, NG/propane availability, regulatory and physical constraints; engineering review for actual solution design.
6. **Buying chain:** owner, operator, GC/EPC, MEP/electrical, commissioning contractor, supply decision maker, contact route and *proof of role/authority*.
7. **Next action:** qualified discovery question, authorized contact target or source to watch.

**Fuel caveat:** a flare/vent permit is not proof of recoverable gas flow, composition, continuity, legal reuse, generator suitability or a purchasing need. Similarly, a data-center planned full-load MW is not temporary power demand.

### 7.2 Question registry

Maintain a small versioned set of `research_question` types tied to existing power-need records, e.g. `UTILITY_ONLINE_DATE`, `TEMP_LOAD_MW`, `CONSTRUCTION_START`, `COMMISSIONING_WINDOW`, `NATURAL_GAS_AVAILABILITY`, `DIRECT_BUYER_AUTHORITY`. The queue consumes a **missing evidence question**, not a generic request to "research this project." Reuse present enrichment runs and attributed buying-chain tables; only extend them when existing schema cannot represent required provenance.

Each question stores `source_candidates`, allowed sources, max steps, max time, model route, budget reservation, last attempted, results, exact citations, outcome `FOUND/CONFLICT/UNKNOWN/BLOCKED`, and refresh trigger. No fake answers to make workflows green.

### 7.3 Model routing by difficulty

| Situation | Processing route |
|---|---|
| Structured permit fields or known official ID | Deterministic parse only |
| PDF with difficult narrative details | Fast structured-extraction LLM, citation alignment + validation |
| Two similarly named projects, weak overlap | Deterministic candidate set → Jev advisory → more official evidence / human review |
| Record suggests electricity but not a specific temporary need | Jev use-case hint → question queue; no accepted power claim |
| Meaningful project change with missing buyer/utility info | Jev research priority → deterministic budget gate → OpenAI targeted research |
| Conflicting energization or project-stage dates | OpenAI reasoning reconstruction + source credibility rules → retained conflict until resolved |
| Need to compute MW or duration from accepted dates and supply | Versioned deterministic calculation only |
| Draft call brief or executive explanation | OpenAI synthesis from **validated claim bundles**, with citations |
| Source restrictions, unsupported facts, auth/permission conflict | Stop, record `BLOCKED`, human escalation; no model workaround |

### 7.4 Fast extractor contract

All generated candidates must include `field`, `value`, `unit`, `source_evidence_version`, `quote_or_span`, `page_or_section`, `speaker/publisher`, `source_date`, `inference_flag`, `ambiguity`, `validation_state`. Example:

```json
{
  "field": "planned_utility_energization",
  "value": "2028-Q3",
  "unit": "calendar_quarter",
  "evidence_version_id": "uuid",
  "span": "...anticipated service during Q3 2028...",
  "page": 4,
  "extraction_kind": "directly_stated",
  "validation_state": "CANDIDATE"
}
```

Exact-source checks must confirm the cited span and acceptable value/unit. A model-calculated number or inferred date remains a **hypothesis**, not an accepted fact, until grounded and verified. Missing fields are `UNKNOWN`, not zero. Conflicting claims remain plural and attributable.

### 7.5 Deep research contract

Input: bounded project dossier, question(s), accepted and conflicting evidence, allowed source types, external-retrieval budget, region, context of commercial fit. Output: `hypotheses`, `new_cited_facts`, `contradictions`, `unresolved_questions`, `candidate_organizations`, `next_source_queries`, `suggested_pursuit`. Retrieval results must be actually fetched and preserved; no citations invented from URLs the model did not inspect. Any discovery of a potentially new authoritative source returns through the usual evidence admission pipeline.

## 8. Evidence, identity, change and commercial tier gates

### Evidence model

- Keep stable **Observation** identifier per external source object and immutable **Evidence** versions keyed by source/version/content state.
- Store received timestamp, source publication and described event dates separately; never treat *retrieved today* as *happened today*.
- Attach each candidate and accepted claim to exact evidence version and extraction location. Annotate `SUPPORTED/CONFLICT/UNKNOWN` per material field.
- Preserve corrections, source withdrawals, rejected merges and reversals as separate audit events. No destructive rewriting of historical truth.

### Identity resolution order

1. Exact authoritative project or permit identifiers.
2. Reliable normalized address, coordinates and publisher-backed project IDs.
3. Deterministic multi-signal matching with explicit negative evidence.
4. Jev judgment **only across a narrow candidate set**.
5. Source/research corroboration or human review for uncertain merges.

Never merge by company name, city, similar project title or model assertion alone. Keep project aliases and historical associations traceable.

### Change semantics

Use already documented `project_material_states`, `change_events`, and project state/changes API patterns, not a new event mechanism. Compare accepted **semantic state** (including relevant withdrawals) against prior accepted state. Suppress metadata-only churn; preserve A→B→A reversions. Source version changes alone need not imply commercial progress.

### Tier separation

- **Signal:** source-backed reason to investigate a project-specific need; unknown MW can remain unknown.
- **Prospect:** supported power requirement and evidence suggesting suitable supply may be insufficient at relevant timing.
- **Lead:** defensible **remaining** MW range, start window, duration range and evidence for an unresolved supply gap as required by existing PRD/policy.
- **Priority/action:** different axis: `ACTION NOW / RESEARCH / WATCH / REJECT` and pursuit status are not tier substitutes. Keep all existing narrower canonical gate semantics.
- User-confirmed facts may count only if attributed and authorized under existing rules; a model assertion alone never satisfies a gate.

## 9. Policy router and spending strategy

**Sequence:** `rules → cache → bounded Jev if ambiguous → cheap LLM extraction if needed → selective deep OpenAI research → validation`. Not every record traverses every stage.

### Candidate cost gates (starting proposal, not live configuration)

- **Zero model calls:** identical content hash, deterministic negative filter, already-covered evidence, or recently completed equivalent question.
- **Jev candidate:** compact ambiguous evidence with source/version-linked context.
- **Fast LLM candidate:** field extraction failed deterministically; high enough source usefulness; valid source content to inspect.
- **Deep OpenAI candidate:** material project delta or commercially valuable unresolved question, supportable buyer/utility hypothesis, no recent identical research, within caps.
- **Human candidate:** material evidence conflict, possible identity collision, risk of losing high-value Signal, sensitive contact action, or a potentially qualified Lead needing review.

Policy controller (pure code) must enforce per-source, per-project, per-model, daily and monthly budgets, provider timeouts, maximum retrieved documents, concurrency, allowed URLs, revisit intervals and maximum retries. Reserve estimated spend **before** an API call, reconcile after using actual usage if available, and fail closed if owner-set budgets are zero. **Never infer token counts or cost from response time.**

### Simple priority rule

Let a deterministic gate rank research urgency using **provenance-rich features**: time since event, evidence materiality, source reliability, relevant lifecycle stage, specific power questions, direct-buyer reachability, potential commercial size (if independently supported), previous attempt freshness, and research cost. Jev's ordinal assessment can be **one feature**, not the final arbiter. Prioritize recall of actionable opportunities over indiscriminate model-call reduction.

## 10. Prompt and context governance

- Each LLM or Jev task gets a versioned **contract**: task objective, bounded inputs, output schema, disallowed assumptions, citation rules and failure behavior.
- Construct contexts server-side from accepted facts and exact evidence excerpts; strip boilerplate and irrelevant text. Prevent raw web pages from injecting instructions into models or tools.
- Treat all source content and model output as **untrusted data**. No instructions extracted from source documents may modify worker permissions, budgets, endpoints or retrieval limits.
- Separate `candidate`, `reviewed`, `accepted`, and `rejected` states. Do not mutate accepted facts by editing prompts alone.
- Use explicit `UNKNOWN` and `CONFLICT` values. Require quote-to-source validation for meaningful claims.
- Pin provider model version, extraction/decision contract version and policy revision per persisted run to make replay and drift evaluation possible.
- Retain minimally necessary prompts/results under approved source terms; avoid logging secret values, private notes, full raw artifacts or personally sensitive details.

## 11. Benchmark and evaluation plan

### 11.1 Build a labeled, representative corpus

Use existing historical GL3 corpus and owner-reviewed examples. Stratify by source type (structured permit, PDF, utility filing, contractor news, procurement, O&G flare/vent record), vertical, location, ambiguity, claim conflicts, rejected/noisy sources, projects with similar names, unknown temporary MW, later corrections and source outage. Include known **commercially important positives** that would be costly to miss. **Labels must be assigned without leaking candidate model answers**.

Compare at least four end-to-end routes on the *same frozen sample*:

1. Current rules and existing GL3 paths.
2. Rules + Jev advisory.
3. Rules + fast LLM only for needed extraction.
4. Rules + Jev routing + fast extraction + selective deep research.

### 11.2 Metrics and suggested release gates

| Dimension | Measure | Release logic |
|---|---|---|
| Commercial recall | % of labeled material power-need events preserved for review | **No unacceptable missed high-value source**; set numerical floor before test |
| Precision | Share of surfaced signals that genuinely match specified review criteria | Must improve useful daily list vs baseline without harming recall |
| Entity matching | False merge count and false split count | **Zero known unsafe auto-merges**; ambiguous cases remain unresolved |
| Claim quality | Exact quote alignment, unsupported MW/dates, conflict retention | **Zero fabricated authoritative facts in acceptance corpus** |
| Tier correctness | False Prospect/Lead promotions, unsupported utility shortage | **Zero model-caused bypasses** of deterministic gates |
| Jev health | Valid schema %, timeout/invalid, p50/p95, disagreement classes | Track by decision contract and model version |
| Full pipeline | Source freshness, time-to-visible change, queue age, job retries | Measured versus agreed freshness SLOs, not UI impressions |
| Economics | Provider cost per 1k changed documents, per useful Signal, per qualified pursuit | Show whether routing actually beats rule/LLM baseline |
| Research return | % escalations adding independent grounded facts, cost per resolved question | Discontinue low-yield question types |
| Operational robustness | Restart recovery, retries, lease fencing, zero-budget no-call, backup restore | Pass explicit fault and restore tests |

**Numerical thresholds are deliberately not invented.** Record frozen corpus, class prevalence, owner cost tolerance and baseline performance first. Add explicit quantitative p95, recall, precision and spending thresholds as a separately accepted evaluation fixture. Staging/fixture pass is not production acceptance.

### 11.3 Adversarial tests

- A campus with 100–500 MW permanent load but **no** cited temporary need.
- Permit applicant mistaken for purchasing authority.
- Two different facilities with similar names and nearby addresses.
- A flare authorization mistaken for accessible continuous generator fuel.
- A contractor article reposted by many outlets, appearing as multiple independent sources.
- A utility press release with no site-specific energization commitment.
- A document changes metadata while commercial content is identical.
- Source withdraws/corrects a previously accepted date.
- Provider timeout after the job reservation is durable.
- Malformed or out-of-schema Jev reply.
- Retrieved text tries to override system instructions / reveal credentials.
- Live feature flags disabled and budgets zero: **zero network model calls and zero model cost**.

## 12. Rollout plan: small slices with exit criteria

### Phase 0 — Exact-state audit and baseline (**must precede enablement**)

Inspect current `main` at SHA: all Jev adapters, flags, current secret forwarding, source registry, queue, existing research/enrichment, projection coupling, Graph/EvidenceJudge logs, the October 18 removal work and deployment configuration. Verify whether the live app is identical to repo current main. Inventory current enabled sources and exact user-authorized budgets. Gather frozen labeled baseline; record zero-budget behavior. **Exit:** verified dependency/ownership map, corpus, baseline, measured current production flags. No provider activation.

### Phase 1 — Consolidate Jev decision contracts (no new platform)

Integrate a small typed, versioned catalog into existing Jev integration while preserving **separate authority paths**. Compare overlap between current Signal adjudication and EvidenceJudge; avoid redundant calls. Make exact pinned vendor-schema tests, provider health, model/version, evidence digest and failure fallback explicit. **Exit:** replayable shadow decisions, strict schema validation, no project/tier state change, no repeat after interrupted PENDING reservation.

### Phase 2 — Efficient classification + extract only when needed

Optimize no-change short circuit, deterministic parsers, compact question context, and model-call routing. Integrate or harden grounded extraction for unstructured sources that demonstrably fail current parse. **Exit:** source-based regression tests, no lost high-value events, accepted-fact checks, cost/latency measurements, no invented MW.

### Phase 3 — Question-driven enrichment and OpenAI reasoning

Route top unmet commercial questions through existing project-scoped enrichment runs and durable queue. Add one controlled strong-reasoning path for actual difficult cases; validate sources and compute gap with code. Preserve current buying-chain distinction and evidence version binding. **Exit:** at least one real attributable changed-source → bounded research → saved citation → revised project/need → owner-visible next action, without unsupported tier promotion.

### Phase 4 — Controlled Jev routing activation

Only after corpus evaluation, enable lower-risk Jev routing for **bounded research allocation** behind explicit budget and emergency kill switch, with rollout limited to chosen sources/verticals. Compare baseline and enriched cohorts; rollback if recall or unit economics worsen. **Exit:** measured improvement without false Lead promotion, identity corruption or missed priority events.

### Phase 5 — Cloud operations and commercial acceptance

Independently prove authorized **PC-off scheduling**, real collection/persistence, retry, health alerting, backup/restore, seven consecutive actual daily cycles, and one independently discovered legitimate power need reaching appropriate qualification using supported real evidence and owner review. **Exit:** satisfy canonical PRD operational gates; no substitution of model benchmarks or staging runs for live acceptance.

## 13. Builder work packages and ownership

These are **work packets**, not instructions to execute everything in one PR.

| Packet | Scope | Dependency | Minimum verification |
|---|---|---|---|
| **A — Audit** | Exact SHA inventory; current provider routes and flags; source, job, enriched evidence and data contracts; deployment differences | None | Findings with links, no changes to production state |
| **B — Jev contracts** | Typed versioned decisions, existing path consolidation, input digest, health metrics, strict fallback | A | Contract/fixture, unknown response, timeout, PENDING retry tests |
| **C — Ingestion efficiency** | No-change skip, bounded contextualization, source quality and incremental fetch | A | Replay determinism, source failures, concurrency/load measures |
| **D — Grounded extraction** | Structured candidate claims and citations; explicit unknown/conflict | A/C | Quote-verified field cases, false extraction regression tests |
| **E — Selective research** | Budgeted questions, deep OpenAI research, validation, buying-chain and utility facts | B/D | Real retrieval cited, policy limits, queue persistence, budget zero proof |
| **F — Commercial output** | Accepted facts, gap calculations, decision diff, meaningful next action surfaced in existing UI | E | Real project journey with supported need, no fake Lead |
| **G — Ops acceptance** | Authorized cloud cadence, credential wiring, observability, restore, alerts, measured daily cycles | A–F | Production receipts, alerts, restarts, restores, owner review |

**Guardrails for builders:** implement on short feature branches from exact main, pin candidate SHA, preserve unrelated work, run isolated database tests, avoid undeclared schema migrations, maintain changelogs/decision records only as needed, independent code review and exact-head checks, and promote/deploy only under owner-authorized controls. In particular, do not disrupt the October 18 editorial removal or merge unrelated newsletter PRs.

## 14. Operations dashboard and alerts (data, not decoration)

One compact authenticated operations view should show: **last completed source cycle**, number of sources due/checked/failed/partial, oldest expected record, retrieval/parse success, queue backlog/oldest job, Jev model/version + calls/errors/p95, fast/deep model use and spend, enrichment questions resolved vs unknown, source-backed material changes, reviewed meaningful Signals, independent Leads, and last successful backup/restore. Separate `configured`, `enabled`, `called`, `completed`, and `accepted` states. Never label Jev "healthy" solely because a secret exists.

Alert when a critical source misses freshness window, many sources fail parsing, provider error rate spikes, budgets unexpectedly exhaust, job lease stalls, model invalid outputs climb, recall regression appears, or backup verification fails. Alert destinations and actual activation remain owner authorized.

## 15. Security and safety requirements

- Secrets from the approved secret manager/environment only, never source code or logs. Verify present **runtime** propagation to API/worker (not simply stored in config).
- Bound and allowlist external HTTP access; respect ToS, robots/official access constraints as applicable, data licensing and retention. No model-generated URL may silently escape the retrieval allowlist.
- Scrub malicious instructions from documents as data, isolate tools, validate outbound requests, keep network egress within policy and authentication server-side.
- Use least privilege: Jev has no write/research powers; extraction cannot accept; deep research has read/retrieve scope only; authenticated domain operations alone mutate canonical state. All contact or outreach stays owner approved.
- Apply per-tenant/person data minimization; do not treat scraped contacts as verified employees or buyers without dated authoritative support.
- Maintain kill switches for each provider, decision contract and research queue, with safe degradation to last-good deterministic mode.

## 16. Key decisions to freeze now

1. **Jev is an advisory decision service, not the system of record.** Its first production-capable authority is *bounded research routing* only, after evaluation.
2. **OpenAI is the deep investigation and synthesis layer**, called selectively; the cheaper extractor is for grounded field recovery only.
3. **Domain code owns all facts, exact calculations, gates, storage and effects.** No probabilistic model qualifies a Lead by itself.
4. **Broad acquisition is separate from targeted monitoring.** Work from changed source versions; never re-run every model on unchanged data.
5. **Enrichment is question-driven, evidence-preserving and budgeted**, not an endless research agent.
6. **No speculative new infrastructure.** Extend existing FastAPI/worker/PostgreSQL and current Jev adapters. No new graph/vector database or framework until a measured constraint justifies it.
7. **Production enablement requires distinct authorization and verified operation**. Existing status reports show critical live functions off/unproven; this document does not turn them on.
8. **No editorial resurrection** within intelligence integration.

## 17. First implementation instruction to the GL3 builder

> Audit the exact current `gl3/main` and live release; map the existing Jev Signal adjudicator, EvidenceJudge shadow path, provider health/secret forwarding, durable job/ingestion state, autonomous research and existing enrichment records. Treat the PRD and October 1 evidence graph/October 18 editorial-removal decisions as binding. Implement **Packet A only**, returning (1) verified current architecture with source links and exact SHAs, (2) duplicated pathways and reliability/performance bottlenecks, (3) a labeled corpus and proposed measurement plan, (4) a minimal dependency-ordered PR plan, (5) operational/permission blockers. Do not activate Jev, OpenAI paid research, live collection or schedules; do not modify production data, reintroduce editorial, or relax tier gates. Once Packet A is accepted, deliver the smallest reversible, independently testable integration slices described above.

---

## Primary project references

- [`docs/product/PRD.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/product/PRD.md) — product and tier requirements.
- [`docs/architecture/evidence-graph-jev.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/architecture/evidence-graph-jev.md) — canonical evidence graph and Jev architecture.
- [`docs/architecture/overview.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/architecture/overview.md) — current app boundaries.
- [`docs/delivery/milestones.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/delivery/milestones.md) — recorded operational gaps and acceptance gates.
- [`docs/validation/gl3-028-evidence-graph-jev-shadow.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/validation/gl3-028-evidence-graph-jev-shadow.md) — dated EvidenceJudge validation, API-contract reference.
- [`docs/sources/gl3-019-permit-enrichment.md`](https://github.com/nrsandoval1231-oss/gl3/blob/main/docs/sources/gl3-019-permit-enrichment.md) — bounded permit enrichment and provenance.
- [Official TypeSafe API reference](https://api.typesafe.ai/redoc) / [OpenAPI specification](https://api.typesafe.ai/openapi.json) — verify live Jev model, choice/score/noul shapes, limits, pricing and version before implementing or enabling provider calls.

**Implementation principle:** **Jev chooses what warrants attention. OpenAI investigates what it means. Evidence and deterministic policy decide what GridLens can assert or do.**
