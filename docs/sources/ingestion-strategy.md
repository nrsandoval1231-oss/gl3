# GridLens ingestion strategy

**Date:** September 24, 2026  
**Status:** Owner-approved implementation direction; source readiness and operational results remain unproven.  
**Applies to:** The fresh `gl3` implementation.  
**Product authority:** [PRD](../product/PRD.md).

## Objective and priority

Prove that GridLens consistently discovers new projects and detects material changes before adding n8n research workflows. The PRD already specifies many reliability requirements. Actual source selection, production access, completeness within declared collection windows, and commercially useful output still require evidence.

A scheduled job running successfully is only one part of ingestion success. Failures must be visible and recoverable. Public information cannot guarantee discovery of every project or power requirement; coverage limitations must remain explicit.

This strategy elaborates the PRD's ingestion and verification requirements. It preserves national, cross-industry collection with default priority for data center construction and commissioning. It does not import any old GridLens implementation.

## Six guarantees to demonstrate

| Guarantee | Required evidence |
|---|---|
| Coverage | Declared industries, geographies, source families, and project events for every source, with known gaps. |
| Discovery | Previously unknown projects and events found without supplying their project names. |
| Freshness | Newly published information and changed records detected without presenting old news as new. |
| Integrity | Source identifiers, relevant dates, and permitted supporting content preserved; retries do not duplicate observations or project cards. |
| Recovery | Source failures, parser failures, and interrupted workers leave visible unfinished work that resumes safely. |
| Commercial usefulness | Observations provide a defensible reason to investigate a specific power need rather than merely collecting companies. |

## Three complementary collection paths

### Broad discovery

Find new projects and events across the national scope through a mix of:

- Structured regulatory and industrial records.
- Construction and permit publications.
- Developer and contractor announcements.
- Utility and regulatory material.
- News and economic-development publications.

For each source, answer: **What event can this reveal, and why might that event matter for power?**

Search queries supplement this coverage. Ranked search results do not establish that every new record was checked. Query variants against the same publication do not count as independent feeds.

### Targeted project monitoring

After discovering a project, monitor its relevant sources for:

- Construction and commissioning milestones.
- GC, EPC, and electrical-contractor awards.
- Utility service dates and changes.
- Onsite generation and temporary-power awards.
- Delays, cancellations, and completed energization.

Broad discovery finds projects; targeted monitoring keeps their records useful. Retain separate power needs for separate project activities. A campus's eventual operating load is not automatically its construction or commissioning requirement.

### Reconciliation and backfill

Periodically recheck overlapping publication windows. Reconcile stable record IDs, counts, or historical listings where the source exposes them.

This path catches late publications, revised records, pagination mistakes, and information missed during outages. Preserve checkpoints and the source-specific collection window. Where completeness cannot be checked, document that limitation rather than claiming exhaustive capture.

## Source readiness gate

A configured URL is not a working source. Before counting an adapter as active, demonstrate:

1. Real retrieval using the intended production access method.
2. Parsing and evidence persistence, including publication dates when available.
3. Complete pagination or downloads within the declared collection window.
4. Replay of identical input without duplicate observations or cards.
5. Detection of a changed record while preserving prior evidence.
6. Visible failure when access or document structure changes.
7. Useful observations inspected against the original source.

Do not equate an HTTP success with successful ingestion. A login page, unexpected empty response, or broken parser must not receive a false success.

Distinguish a legitimately unchanged monthly dataset from a parser finding zero records. Record last attempt, last successful check, underlying publication date, new and changed counts, parse errors, and reason for failure.

## One ingestion execution system

Retain the PRD architecture:

**Managed scheduler → PostgreSQL jobs → Python worker → preserved observations → validation and project matching.**

The Python worker and durable jobs own checkpoints, bounded retries, timeouts, job leases, source status, and crash recovery. Persist collected observations even when an LLM is unavailable; leave interpretation and research queued.

Keep qualification, arithmetic, and priority in deterministic domain code. Collection emits observations and does not independently award a Lead tier.

Introduce n8n only when a specific connector demonstrably reduces implementation effort. Document that integration decision explicitly. Do not split source scheduling and authoritative run status across two systems while establishing ingestion reliability. The earlier n8n research-workflow proposal is deferred behind this work.

## Coverage matrix before expansion

Create and maintain `docs/sources/coverage.md` from actual source evaluation. Keep proposed, access-tested, validated, disabled, and active sources distinguishable.

The matrix should capture:

| Field | Purpose |
|---|---|
| Stable source ID, publisher, URL or endpoint | Identify and trace the source. |
| Source family, geography, industry | Show actual coverage and gaps. |
| Project event and power relevance | Explain the commercial reason to collect it. |
| Retrieval method, access limits, retention notes | Establish practical production access. |
| Publication cadence and check cadence | Separate source freshness from collection frequency. |
| IDs, pagination, collection window, reconciliation method | Describe how capture and completeness are assessed. |
| Real sample, parser, and readiness evidence | Demonstrate retrieval through persistence and replay. |
| Unique useful observations, failures, and cost | Guide expansion using observed value. |
| State and known limitations | Prevent planned feeds from appearing operational. |

Use the existing versioned source registry for execution configuration. Runtime source health belongs in durable application records; documentation must not become a competing run-status database.

## Verification and launch evidence

Retain the existing PRD launch gates:

- At least **12 independent active feeds across five source families**, including **two national structured sources**.
- Real relevant Signals across **three industries**.
- A retained review sample of **30 independently discovered Signals/Prospects**, targeting at least **24** with correct identity, supported events, and defensible power relevance.
- **Seven consecutive scheduled daily runs**, with at least **95%** of due checks verified successful overall.
- No source missed for two consecutive daily cycles without a visible alert; no unreported failures.
- Demonstrated restart/replay, backup restore, visible operating cost, and backlog.
- Every initial Lead reviewed against all required evidence fields; incomplete records are not promoted to meet a target.

Add these coverage checks as part of ingestion validation:

### Historical discovery check

Select and retain a dated sample of known project announcements and material changes. Determine whether the configured sources and collection windows would have captured them. Record misses and their causes.

Use the result to assess observable coverage. A historical sample does not prove nationwide completeness or that a live pipeline already captured those events.

### Live discovery check

Run collection without supplying project names. Inspect independently found projects, duplicate reporting, known misses, and each source's unique useful evidence contribution.

Historical examples and test fixtures must remain distinguishable from actual live discoveries.

## Daily operating view

The ingestion view must answer:

- What was due?
- What completed?
- What failed or became overdue?
- What changed?
- What remains unprocessed?
- Where is coverage weak?

Show **Checked—No Change**, **Updated**, **Failed**, and **Overdue** distinctly. A healthy overall percentage must not hide a repeatedly failing source. Budget pauses and processing backlogs must remain visible while the last valid data stays available.

## Execution sequence

1. Evaluate the initial sources and produce the coverage matrix with actual access and sample-record evidence.
2. Build one complete path from retrieval to preserved observations, replay, and visible source health.
3. Exercise that path with one structured source, one web publication, and one document source.
4. Expand through the same adapter interface while maintaining national discovery and construction/commissioning priority.
5. Run historical and live discovery checks; repair demonstrated coverage and integrity gaps.
6. Complete the PRD's source-breadth, sample-quality, operational, and commercial gates.

The first three source types establish implementation behavior; they do not satisfy the full launch coverage requirement.

## Completion standard

The immediate deliverable is a **validated source coverage matrix and a working end-to-end ingestion path**. Documentation, adapter count, execution count, and test count alone do not establish readiness.

Report source evidence, useful discoveries, replay and recovery results, costs, and remaining coverage limitations. Expand based on measured usefulness and reliability.
