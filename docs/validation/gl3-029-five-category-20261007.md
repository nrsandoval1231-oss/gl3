# GL3-029 — five-category regenerated-corpus validation

October 7, 2026. Draft PR24 remains unmerged. Tested code:
`92f7689544c6e72929615e3cad1a012fa38e5caf`; source/config fingerprint:
`2f79ad311a5d9edd585237ff205b61f9a09731fa909159f4293c98f3a178778f`.
The subsequent publication changes documentation/receipts only.

**The unchanged five-category mechanical gate passed 5/5.** Six blockers finished
UNRESOLVED, zero failed, with no commercial or evidence-tier transition. This proves
bounded, inspectable unresolved outcomes on fresh real data; it does not prove that
research resolved these commercial unknowns. The two Austin cases use the existing
owner-accepted no-question/no-change exception. Original PR23 retained-corpus proof
remains false; the owner superseded archive recovery with fresh regeneration.

## What changed

The previous repaired four-case result remains in
[its dated report](gl3-029-regeneration-repair-20261007.md). The owner subsequently
approved the existing RRC anonymous public-download form POST. The native adapter
successfully downloaded daily/monthly snapshots on its first attempt, using six
requests between 02:58:29 and 02:58:33 UTC. No login, purchase, new credential,
access-control bypass, outreach or deployment occurred.

The snapshots yielded 1,107 canonical parsed records, 1,101 eligible Signal
assessments, 1,010 approved drilling records, and six rejected assessments. These
are parsing/screening counts, not 1,107 researched or persisted opportunities.
Exactly one selected drilling record was ingested through the existing fenced
Observation/Evidence/Interpretation/Project/PowerNeed pipeline: RRC `0919039`,
Sage Natural Resources LLC, Pedro West EF well 1H, issued October 5. It is a WATCH
pursuit and Signal. Permit approval does not prove drilling underway, a temporary
power requirement, load, supply adequacy, or a buyer.

The minimal additional capability inspects complete RRC native bytes already
retained in Evidence. It reuses the native parser/renderer; requires current accepted
interpretation, exact source/project/need binding and unique observation linkage;
verifies base64/hash/provenance, full canonical text, dates and extraction location;
and bounds work to 20 segments and 750,000 encoded/decoded bytes. Opaque children
remain uninterpreted. Filename/ordinal are preserved ingestion provenance, not
independently verified snapshot authenticity. No new claims or evidence are created
by this inspection. The receipt uses original acquisition time, a separate inspection
time, `retained_native_replay:true`, and `network_refresh:false`.

RRC still has no autonomous exact-record network refresh in this slice. Missing
broader discovery remains visible; existing bounded transient retries and exhaustion
remain unchanged. No validation predicate, tier rule, commercial evaluator, or schema
was modified for this final repair.

## Five real cases

Run: **03:11:33.509467–03:11:50.906189 UTC** in isolated
`gl3_regen_20261007_five_run`. Source corpus: 15 Observations/Evidence and 14
Project/Signal PowerNeeds. All five selected cases remain Signals.

| Case | Before → after | Research outcome |
|---|---|---|
| Austin data center, 811 Clayton Ln, 2026-036762 EP | ACTION NOW → ACTION NOW | Existing canonical contact/activity support; no new questions, no change, narrow owner exception |
| Austin explicit temporary power, 833½ E Braker Ln, 2026-127192 EP | ACTION NOW → ACTION NOW | Existing explicit temporary-power permit; no new questions, no change, narrow owner exception |
| Chicago conversion, 400 S La Salle, 3451848 | RESEARCH → RESEARCH | Two blockers UNRESOLVED after native checks; no current power requirement or phase answer invented |
| O&G, RRC 0919039 | WATCH → WATCH | Two blockers UNRESOLVED after verified retained native inspection; no live source refresh or broader search claimed |
| Low quality, 2800 S Ashland, 3428005 | RESEARCH → RESEARCH | Two blockers UNRESOLVED after native checks; old cooling/MEP scope does not prove a current temporary-power package |

The [machine-readable report](gl3-029-five-category-20261007.json) contains each
initial/final state, known facts, exact question, generated queries, source checks,
original retrieval and inspection timestamps, accepted/rejected/unresolved outcomes,
budgets, remaining unknowns, evaluator reasons and recommended next actions.
Generated queries are not executed searches. No new external evidence was admitted
by these six attempts; existing native document versions were reused.

Baseline selected cohort: two ACTION NOW, two RESEARCH, one WATCH; zero questions.
Final: three pursuits investigated via validation-origin jobs; six attempted blockers,
zero resolved/partially resolved, six unresolved; two native HTTP retrievals,
zero executed searches/model calls, $0 recorded provider cost, four duplicate-work
avoidance events, zero failures, median question latency **1.2725 seconds**.
Average retrieval attempts per blocker: 0.3333; one checked URL per blocker, including
retained checks. Six explicit reevaluations completed; zero ACTION NOW/WATCH/REJECT
transitions, zero Signal→Prospect or Prospect→Lead promotions. This was an explicit
local validation run, not demonstrated unattended overnight operation.

## Provenance, replay and preservation

The original fresh source database remains preserved. Its five-case copy and the
post-research copy both passed exact inventories across all **28 public tables**.

- Raw canonical RRC record-set SHA256:
  `65437a8ef972ce17db701220f79cf9dd1b9f199c9c3939e7bb63ed6f75ec935e`.
- Pre-research backup SHA256:
  `2dd076348e03a5b0415b668d11befadc9b5bb7382a05cd7187d845557c6b7f5b`.
- Post-research backup SHA256:
  `0d01f941071c35dbd9f6ce3bac903cc53ab1388f092e5e53a7c23337973a5975`.
- Baseline digest:
  `b7c08b3d58de84a13471efad38b77da5aeb250bd845e67c8da422952f1d60243`.
- Exact replay before/after digest:
  `39d69cdc8a92acec303346f08445766c6308258dfa2b9d97aba0492fddcee44a`.

Replay would create zero questions. All 15 Evidence rows, historical evaluations,
project/need identities and call-note inventory were preserved. No original database
was reset. All 1,107 downloaded native records also reconstructed field-for-field
offline; that is parser consistency proof only. Raw snapshots, full canonical data,
backups and screenshots stay ignored; the report publishes their hashes and bounded
claim excerpts. Earlier failed runs remain unchanged.

## Final candidate gates

| Gate | Exact result |
|---|---|
| `uv run --directory backend ruff check src tests` | Passed |
| `uv run --directory backend mypy src` | Passed, 77 source files |
| `uv run --directory backend pytest tests` | **1,229 passed, 1 skipped**, one existing Starlette/httpx deprecation warning; 161.04 seconds |
| Focused validator/regeneration suite | **71 passed**; included in full suite |
| RRC parser/reconstruction unit suite | **52 passed**; included in full suite |
| RRC canonical integration cases | **9 passed**; included in full suite |
| Frontend typecheck/build | Passed |
| `npm --prefix web audit --audit-level=high` | Zero vulnerabilities |
| OpenAPI contract | Exact match |
| Browser regression | **36 passed**, 38.8 seconds |
| Actual-database browser checks | **5 groups passed**: authentication, Chicago history, O&G history including no-live-refresh disclosure, low-quality history, mobile reload |
| Five-category unchanged validator | **5/5 accepted**, six UNRESOLVED, zero FAILED |
| Exact replay and immutable preservation | Passed |
| Independent adversarial code/receipt review | No material findings |

The single backend skip is the existing optional North Carolina live probe. New tests
exercise corrupt hashes/base64/provenance, conflicting sequences, bounds, nested JSON,
wrong/ambiguous bindings, stale interpretation, exact replay, truthful dates, zero
network inspection and unchanged Signal/MW/supply. The minor review finding for deep
JSON recursion was fixed and regression tested before candidate freeze. The independent
reviewer inspected code and receipts; the executor ran the tests.

Migrations: fresh empty database→0014, populated isolated 0013→0014, repeated upgrade,
and no-drift checks all passed. The populated round trip preserved all 28 table
inventories exactly. No migration changed. A temporary verification harness initially
used the wrong inventory key while writing its summary; it was corrected, checks
rerun, and a separately fresh clean database verified. No product migration failed.

## Reproduction and remaining limits

Use the existing environment and isolated databases; never print credentials or run
destructive tests against source/acceptance data. `scripts/regenerate_pursuit_corpus.py`
provides snapshot/backup-restore; `.artifacts/regeneration/five-manifest.json` binds
five exact need IDs to the isolated run database. Freeze code before running:

```bash
python scripts/validate_pursuit_research.py baseline \
  --manifest .artifacts/regeneration/five-manifest.json \
  --baseline <new-baseline-path> --corpus-id gl3-029-fresh-five-20261007
python scripts/validate_pursuit_research.py run \
  --manifest .artifacts/regeneration/five-manifest.json \
  --baseline <new-baseline-path> --report <new-report-path> \
  --corpus-id gl3-029-fresh-five-20261007 --execute --allow-public-research
```

Use a newly restored database/manifest for a new before/after experiment; do not
overwrite original receipts. The saved executor wrapper `/tmp/gl3-regen-run.py` selects
existing configuration, isolated database, disabled paid providers and $0 budget.

Six named historical live-browser prerequisites remain unavailable, so those legacy
checks were not run or relabeled as fresh proof. Firecrawl discovery/model providers
were not enabled; zero searches is a limit, not an exhaustive negative. RRC does not
get a network research route from retained reconstruction. The tested real cases show
honest unresolved behavior; positive commercial/tier transitions remain supported by
deterministic fixtures, not claimed from this live run. No external commercial
outreach occurs. Cloud deployment and production-proven unattended operation remain
separate milestones.
