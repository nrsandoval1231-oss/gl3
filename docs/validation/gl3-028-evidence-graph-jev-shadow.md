# GL3-028 evidence graph and EvidenceJudge shadow

## Delivered behavior

`GET /api/projects/{project_id}/state` returns a bounded current projection of accepted, evidence-version-bound state. Unsupported values remain `UNKNOWN`; conflicting accepted claims remain explicit. `GET /api/projects/{project_id}/changes` returns immutable material transitions. Migration `0012` adds the event and accepted-state snapshot storage; project-scoped serialization compares actual prior and new state, suppresses metadata-only churn, and preserves reversions as new revisions. Ordinary material changes and accepted retained-source withdrawals reference their source `Evidence`; externally supported contractor/buyer changes instead set `buying_chain_evidence_id` to the immutable buying-chain record that supports that field and leave generic `evidence_id` unset. Contractor/buyer removals use checked replacements at the prior claim URL where available; the partial-removal case is covered by a focused regression. The morning `/api/changes` endpoint selects the stored source title and URL without changing its response shape.

The EvidenceJudge adapter is separate from the existing Jev signal-adjudication path. It uses strict choice enums, validates the TypeSafe response, sends a compact context, and has no authority over ingestion, project matching, evidence acceptance, power calculations, qualification tiers, or external action. Explicit runtime and fixture benchmark commands require `JEV_ENABLED=true`, `JEV_SHADOW_MODE=true`, and a process-only TypeSafe key. Defaults leave provider evaluation disabled. A persisted PENDING reservation prevents automatic repeat after an interrupted provider call. `research_recommended` is a pure deterministic advisory function over validated judgments and bounded known/missing project facts; it does not enqueue work.

The vendor adapter's response contract was implemented against the [official TypeSafe OpenAPI specification](https://api.typesafe.ai/openapi.json). The downloaded contract snapshot has SHA-256 `A191F8A7DF6BD6FEDCED8120DD0FD106F88575D1D1C8360D08900A6C7C0360D5`.

## Fixture design

The checked-in fixture set contains 16 cases: five retained real cases and eleven synthetic variants. Retained entries use exact project/evidence/source identifiers from the isolated acceptance clone. Their descriptions are summaries, not verbatim excerpts; live benchmark mode obtains title and abstract directly from the selected retained Evidence row. Synthetic cases derive bounded context from a named real case and explicitly label hypothetical content; they are never treated as discoveries and are never written to domain tables.

The cases cover Boston temporary electrical work, Chicago data-center construction, Houston 35 kW work below the inclusive visible-opportunity floor, Austin hospital generator replacement and a Texas RRC drilling permit, plus synthetic same-site/wrong-site matching, backup-generator distinction, construction versus commissioning, explicit commissioning, contradictory utility dates, news-only context, RRC/flare routine work, irrelevant equipment replacement, unknown size, and an already-resolved utility question. Labels that lack a stated prior accepted state or sufficient source support are `UNKNOWN`. Houston's 35 kW evidence remains project-relevant even though its size is below the visible commercial opportunity floor.

This is a small bounded fixture set, not a representative accuracy sample or a human-reviewed gold set. Synthetic and retained-real metrics are reported separately. Expected `UNKNOWN` labels are omitted from agreement denominators; a model `UNKNOWN` for a known label is counted as a disagreement and abstention. Relevance recall includes labeled positives where the model abstains. Coverage, false positives/negatives, invalid outputs, timeouts, latency and measured token usage are reported with their denominators; cost remains `UNKNOWN` unless a provider supplies a measured value.

## Commands and current validation evidence

From the repository root:

```powershell
uv run --project backend pytest backend/tests/unit/test_evidence_judge.py backend/tests/integration/test_evidence_shadow_storage.py -q
uv run --project backend python scripts/evidence_judge_shadow.py --help
```

Focused C/D tests on `gl3_evidence_shadow_test` cover strict provider parsing and pre-transport JSON serialization, enum rejection, usage validation, abstention denominators, durable PENDING resume, valid/invalid/timeout persistence, missing-key/disabled behavior, daily attempt reservation, replay suppression, unchanged accepted project/evidence/tier fields, and the contractor partial-removal evidence reference. Final controller gates on the repaired candidate passed: Ruff, mypy, 587 backend tests with one existing skip, frontend typecheck/build, all six migration checks, `git diff --check`, and 22 browser checks with the isolated worker running. Logs are retained in `.agent/artifacts/GL3-028/validation-final/`. The revised migration preserved all 13 authoritative tables on the retained clone; six-project reopened replay remained `0 → 0`, and all 16,960 Evidence rows matched the original. PostgreSQL shadow tests inject deterministic fake responses and make no provider calls. Exact-candidate acceptance is governed by `.agent/artifacts/GL3-028/REVIEW.json` and `TRANSITION.json`; the parent finish contract remains open. No merge or deployment is claimed.

The controller may run the bounded real benchmark (maximum 16 cases) with a process-injected credential and retain per-case results before and after each call:

```powershell
$env:JEV_ENABLED = 'true'
$env:JEV_SHADOW_MODE = 'true'
uv run --project backend python scripts/evidence_judge_shadow.py --mode benchmark-live --limit 16 --results .artifacts/evidence-shadow/jev-benchmark-results.json --output .artifacts/evidence-shadow/jev-benchmark-report.json
```

The controller ran the benchmark on 2026-10-02 with 16 provider requests. All 16 returned schema-valid results; there were zero invalid responses and zero timeouts. The actual model identifier was `jev-1.13.0`; measured latency was p50 187 ms and p95 375 ms. Token usage was 70,207 input and 5,083 output tokens; monetary cost is `UNKNOWN`. These are fixture comparisons, not claims of model accuracy or a representative sample:

| Case group | Cases | Relevance precision | Relevance recall | Other measured agreement |
|---|---:|---:|---:|---|
| All cases | 16 (15 labeled; 1 expected UNKNOWN) | 10/11 (90.9%) | 10/12 (83.3%) | same project 12/14; power relevance 10/14; temporary hint 6/7; deep-enrichment usefulness 10/14 recommendations |
| Retained real context | 5 | 5/5 | 5/5 | same project 5/5; power relevance 3/5; temporary hint 2/3; deep-enrichment usefulness 4/5 recommendations |
| Synthetic variants | 11 (10 labeled; 1 expected UNKNOWN) | 5/6 (83.3%) | 5/7 (71.4%) | same project 7/9; power relevance 7/9; temporary hint 4/4; deep-enrichment usefulness 6/9 recommendations |

Across labeled relevance cases, there was one false positive, two false negatives, zero model abstentions, and full coverage (15/15). The deterministic research recommendation returned NO for all 16 cases because every model result labeled material change NO; this is an advisory gate outcome, not proof that further research has no value. To rescore retained results without another request, use `--mode benchmark-offline-results --results <saved-results.json>`. The preserved raw result, offline score, and execution receipt are `.agent/artifacts/GL3-028/BENCHMARK_RESULTS.json`, `BENCHMARK_REPORT.json`, and `BENCHMARK_EXECUTION.json`.

The first attempted benchmark run failed while `httpx.post` was preparing the request because nested UUID/date values in project state were not JSON-serializable. The caller was invoked, but no request reached network transport. That failed record set is preserved as `.agent/artifacts/GL3-028/BENCHMARK_FAILED_SERIALIZATION.json`. Recursive JSON normalization was added and verified with a caller stub that serializes the exact request without fallback handling; the successful versioned run above followed. For persisted runtime shadow attempts, use `--mode runtime-live` only against the isolated clone; exact deterministic matches are skipped, so the bounded retained runtime replay produced zero attempts on first and reopened replay. Normal ingestion does not call the provider.

The controller's retained-data replay receipt is `.agent/artifacts/GL3-028/RETAINED_REPLAY.json`. It reports historical current-state replay across six sources with material event count `0 → 0`; this proves quiet replay/backfill behavior only, not a fresh source reread or newly discovered changes. The bounded runtime-shadow receipts show zero provider attempts for exact deterministic matches on both first and reopened replay; ambiguous runtime reservation/persistence behavior was verified with injected provider fakes in PostgreSQL integration tests. Migration data preservation is recorded in `.agent/artifacts/GL3-028/MIGRATION_RETAINED.json`; the final source/clone preservation receipt compares all 13 authoritative tables, with all 16,960 Evidence rows unchanged, at `.agent/artifacts/GL3-028/PRESERVATION_FINAL.json`.

## Limits

The first independent review returned FIX for same-organization role changes: organization-name comparison could select the unrelated permit as support. The repaired selector compares complete projected role rows and their citations, including conflict-derived UNKNOWN relationships. The strengthened contractor transition regression proves general-to-electrical contractor support, unchanged replay, and both contractor/buyer support IDs from the project changes API. That API now exposes nullable `buying_chain_evidence_id` alongside `evidence_id`. The second independent review found a distinct clock-only expiration case: a stored person role could pass the 365-day freshness limit without new source evidence. The repair normalizes solely freshness-expired prior rows whose sources remain current, updates current UNKNOWN state quietly, and prevents unsupported enrichment transitions from citing a contextual permit. Deterministic regressions cover expiry through both ingestion and enrichment, quiet replay, and a positive accepted retained-source withdrawal. Both rejected reviews and manifests remain in the versioned FIX receipts. Prior validation runs remain separately retained; final acceptance is determined by the current review and transition receipts.

One final browser run concurrent with the backend suite produced a timeout in an unchanged mocked project-card case (21 passed, one failed). The unchanged complete browser suite passed all 22 cases with `npm --prefix web test -- --workers=1`; no test or application assertion was weakened. The failed log is retained as `browser-concurrent-timeout.log`; the precise cause of that intermittent timeout is unproven.

No provider cost or production deployment is claimed here. The five retained examples and eleven synthetic variants provide bounded behavioral coverage only. Unsupported load size, utility timing, commissioning, buyer authority, and temporary-power need remain unknown unless the retained source actually establishes them. The advisory recommendation is not authorization to research externally, contact parties, or change qualification state.
