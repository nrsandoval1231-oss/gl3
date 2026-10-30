# Autonomous verification and evaluation

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). This is a TARGET control design. Current deterministic qualification and bounded EvidenceJudge/shadow records are described in [overview](overview.md); no general independent evaluation/promotion system is claimed.

## CURRENT

Existing code includes strict source-scoped qualification, typed fact validation, deterministic demand/supply interval arithmetic, conflict checks, evidence citation projections, logical-call budget/accounting, and optional advisory EvidenceJudge execution. These mechanisms serve specific workflows. They do not by themselves establish independent validation across all seven layers, calibrated abstention, frozen holdouts, or automated model promotion.

## TARGET — independent checks

For each candidate claim/result, an independent deterministic validation stage checks:

1. Source authority, retained evidence/hash, extraction location and date fields.
2. Entity identity and exact project/facility/activity/phase binding; prevent cross-project contamination.
3. Temporal validity, freshness and chronology; event date is distinct from retrieval date.
4. Corroboration independence (same copied source is one source), contradictions, corrections and superseded claims.
5. Typed schema, units, allowed ranges and deterministic calculation recomputation from exact input hashes.
6. Engineering sanity and explicit negative cases, including non-electric drives, standby, mismatched time windows and unknown supply.
7. Commercial rule gates, source citations, contact suppression/privacy, and separation of modeled demand from verified gap.

Model agreement alone is not verification. Validators should use independent deterministic rules, source authorities or external evidence where available. If they cannot establish a required claim, return `UNKNOWN`, `CONFLICTED` or `ABSTAINED`; retain the reason and schedule targeted research only when useful and within configured budgets.

## Evaluation design

Maintain versioned, frozen evaluation sets with adjudicated labels for extraction, entity linking, equipment drive/type, demand range, timing, supply compatibility, buyer authority and opportunity class. Split by source, company/project and time to prevent leakage. Include positive, negative, ambiguous, stale, conflicting, missing-field, adversarial and non-electric cases. Record set hash, label provenance, candidate code/prompt/model/policy versions and evaluator version.

Report per-task precision/recall where labels support them, calibration/error by confidence band, abstention coverage and error, contradiction detection, source freshness, entity contamination, demand interval error, lead precision, contact validity, cost and latency. Overall aggregate metrics cannot hide a safety-critical segment failure. Outcome evidence is delayed and selectively observed; report its coverage and selection bias.

## Promotion, abstention, rollback

Promotion requires predeclared thresholds per task and protected segment, no critical negative-case regression, reproducible evaluation, budget compliance, and a shadow period against the frozen baseline. A candidate that fails remains non-publishing. Rollback pins the prior known-good model/policy/calculation versions and restores their publication eligibility; retain candidate outputs, metrics and reason for audit. Rollback must not rewrite source evidence or delete history. Provider outage, malformed output, budget exhaustion, stale evidence or validator disagreement yields bounded retry, partial result, or abstention—not fallback invention.

## NEXT

First create frozen, source-attributed fixtures for current qualification and new demand models. Then implement independent validator interfaces and read-only shadow evaluation. Define numeric release thresholds only after baseline measurement and owner-approved commercial criteria; never relax thresholds to obtain a pass.

## DEFERRED

Self-modifying code, autonomous policy promotion without a frozen gate, second-model agreement as sole verifier, using user clicks as verified commercial outcomes, or treating production observations as a substitute for labeled evaluation.
