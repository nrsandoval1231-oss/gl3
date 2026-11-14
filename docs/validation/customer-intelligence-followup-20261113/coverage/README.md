# Commercial source coverage follow-up

Capture date: 2026-11-13. Base: `8112fb940c3575b375bdcc0bf471e81bfb0c8830`.

This bounded source-text follow-up adds a typed `campus_development` candidate
for an explicitly named data-center expansion and lets that claim inherit a
subject only from the immediately preceding clause when it contains one unique,
source-native alias in a site/locality construction. It preserves the original
claim quotation and requires the existing claim parser to reproduce the claim
before subject binding can pass. It does not derive an alias from a reference
label, add a basis, or combine the expansion with a campus total.

## Frozen 20-organization replay

The baseline and candidate captures use the same V1 r2 gold hash
`dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922` and source
manifest hash
`4b8831df9e94261806d2df7d51a4df1fd4299fe3b4daf862fdc64b99f192c5fb`. Both
captures include 20 organizations. The replay passes reference project and
location as disclosed oracle scoping context; it does not measure runtime
identity accuracy. Expected capacity/timeline values are scoring labels only,
not extractor inputs.

| Measure | Baseline | Candidate |
| --- | ---: | ---: |
| Raw capacity candidates | 24 | 26 |
| Scoped capacity claims | 2 | 2 |
| Raw timeline candidates | 8 | 8 |
| Scoped timeline claims | 0 | 0 |
| Capacity score, TP / FP / FN (32 references) | 2 / 0 / 30 | 2 / 0 / 30 |
| Timeline score, TP / FP / FN (30 references) | 0 / 0 / 30 | 0 / 0 / 30 |

The only raw increase is STACK's source-reported 60 MW data-center expansion,
found once in each of two retained bundles for the same URL. The repeated source
is not independent corroboration. The candidate remains withheld by the 20-org
replay because its retained native alias set for STACK is empty. A focused test
supplies the source-native `SVY01` alias and verifies that the adjacent site
relation binds the unchanged quote; this is a unit control, not evidence that
the native adapter currently publishes that alias. No improvement to native
admission or customer output is claimed.

The other 19 replay records gained no scoped capacity/timeline claims and no
scored false positives. The separate adversarial controls cover a competing
site, an intervening unrelated clause, a foreign-site relation, ambiguous
basis wording, lease-option wording and contracted offtake.

`baseline-source-scope-replay.json` SHA-256:
`3292247fd0cf7cd5fc1ee2f7bf7f7e83b85b2ba02c8ea9a36d3eab502245b0e1`.

`candidate-final-source-scope-replay.json` SHA-256:
`4f3bb67a471f67c4424e2dbd0210cfb0072d5b2499ef28330b6bc695c01d59dd`.

The Windows checkout materializes hash-bound V1 files with CRLF. For both
replays, tracked V1 files were temporarily restored from their exact Git blobs
and restored byte-for-byte in a `finally` block after each run. Git reports no
V1/V2 corpus changes.

## Checks and limits

- Focused coverage controls: `6 passed`.
- Combined new controls, existing subject-binding tests, and customer-intelligence
  unit tests: `87 passed, 3 deselected`. The deselected cases are the existing
  large-input parameterized test; on this Windows runner its 200,000-character
  parameter ID exceeds the 32,767-character environment limit. A broader run
  also reported two transient assertions during implementation; both were
  corrected before the final focused run.
- Ruff lint and format checks passed on all three changed Python files.
- The native runtime replay was not rerun. Its runner creates a database named
  `gl3_customer_runtime_*_test`, outside this lane's allowed
  `gl3_coverage_followup*_test` database prefix. This lane makes no native
  runtime or retained-data write claim.
- Full CI and the full repository gate were not run.
