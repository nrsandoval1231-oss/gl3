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

- The final 20-organization candidate source-scope replay after verb-first admission
  has the same score as the earlier candidate: 26 raw capacity candidates,
  2/0/30 capacity TP/FP/FN, and 8 raw timeline candidates with 0/0/30 timeline
  TP/FP/FN. `candidate-final-source-scope-replay-verb-first.json` SHA-256:
  `d22469c611cf8ccf8c75ff166114b7823879deb3915c2727362d06bad8288c2b4`.
- Native runtime changed from 4 to 5 accepted interpretations, 4 to 5 project
  rows, and 3 to 4 PowerNeeds; every PowerNeed still has `required_mw: null`.
  The new source-bound record is Lancium Clean Campus, Abilene, TX, from
  Crusoe's retained source. Held documents changed from 18 to 17. No state or
  admission rules were broadened. The account projection remains 3 cards
  (CyrusOne, DataBank, Switch); Crusoe receives no account identity or verified
  buyer contact from this change. All three cards still report
  `unavailable_unverified` contacts. Before receipt SHA-256:
  `3a373ae2b418f182292cf26e93ae51c2416c4a16ecd20f021f5f5d3c41376e66`;
  final receipt [native-runtime-final-verb-first.json](native-runtime-final-verb-first.json)
  SHA-256: `707e81364528ed18da2c94133db56b94262108ac4eaeb9539661218a1d6292b4`.
- Retained-source and verb-first focused suite: `67 passed`.
- The broad `backend/tests/unit` run completed with `3940 passed, 32 skipped,
  20 failed, 41 errors` (119.85s). It was run without `TEST_DATABASE_URL` and
  against Windows CRLF materializations of hash-bound V1 source files. Errors
  include an unparsable missing test URL and V1 source-hash mismatches; this is
  not a clean full-suite acceptance result. The focused retained-source run
  supplied a disposable test URL and temporarily restored exact Git-LF V1
  blobs, then restored each original working byte in `finally`.
- The 3-case parameterized large-input test now has explicit short IDs, removing
  the Windows environment-length failure without dropping cases.
- Full CI and the full repository gate were not run.
