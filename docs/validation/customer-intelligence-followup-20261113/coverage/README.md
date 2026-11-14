# Commercial source coverage follow-up

Capture date: 2026-11-13. Base: `8112fb940c3575b375bdcc0bf471e81bfb0c8830`.

This bounded source-text follow-up adds a typed `campus_development` candidate
for an explicitly named data-center expansion and lets that claim inherit a
subject only from the immediately preceding clause when it contains one unique,
source-native alias in a site/locality construction. It preserves the original
claim quotation and requires the existing claim parser to reproduce the claim
before subject binding can pass. It does not derive an alias from a reference
label, add a basis, or combine the expansion with a campus total.

It also admits a verb-first construction sentence when the retained source
directly names the physical campus and an explicit city/state in that same
sentence. The selected project and location spans are exact source quotes and
are reparsed before admission. Crusoe's retained announcement now yields the
Lancium Clean Campus project in Abilene, TX; company involvement remains
unassigned because the attempted cross-excerpt developer role did not survive
adversarial review.

## Frozen 20-organization replay

The baseline and safe final candidate captures use the same V1 r2 gold hash
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

The only raw capacity increase is STACK's source-reported 60 MW data-center expansion,
found once in each of two retained bundles for the same URL. The repeated source
is not independent corroboration. The candidate remains withheld by the 20-org
replay because the retained native source does not establish a complete
`SVY01` site alias relation. The candidate's source-specific tests also hold
when a named competing campus is mentioned beside generic market language, and
reject partial or punctuation-continued site identifiers. These changes
produce no new scoped customer claims.

The other 19 replay records gained no scoped capacity/timeline claims and no
scored false positives. The separate adversarial controls cover a competing
site, an intervening unrelated clause, a foreign-site relation, ambiguous
basis wording, lease-option wording and contracted offtake.

`baseline-source-scope-replay.json` SHA-256:
`3292247fd0cf7cd5fc1ee2f7bf7f7e83b85b2ba02c8ea9a36d3eab502245b0e1`.

`candidate-final-source-scope-replay.json` SHA-256:
`4f3bb67a471f67c4424e2dbd0210cfb0072d5b2499ef28330b6bc695c01d59dd`.

The safe post-boundary candidate receipt
[`source-scope-safe-final.json`](source-scope-safe-final.json) has SHA-256
`69664a078a02a79ead32107a0615559f186e273d21c7eef768bdfefc07366b61` and
retains the same 20-organization 2/0/30 capacity and 0/0/30 timeline scores.

The Windows checkout materializes hash-bound V1 files with CRLF. For both
replays, tracked V1 files were temporarily restored from their exact Git blobs
and restored byte-for-byte in a `finally` block after each run. Git reports no
V1/V2 corpus changes.

## Checks and limits

- Safe native replay produced 5 accepted interpretations and 5 project rows,
  including Lancium Clean Campus in Abilene, TX, plus 4 PowerNeeds. All 4 have
  `required_mw: null`. Seventeen source documents remain held. No admission,
  region, or company-identity policy was broadened. The account projection is
  still 3 cards (CyrusOne, DataBank, Switch); no Crusoe account, project-role
  claim, or verified buyer contact is emitted. All three projected contacts
  remain `unavailable_unverified`. The final native receipt
  [`native-runtime-safe-final.json`](native-runtime-safe-final.json) has SHA-256
  `b5bfbf2d5a27047e141d7259a4160892e2e2ae14f78137960bb15b2beaf7ae0c`.
- Source-admission regression for the retained Lancium source, including the
  wrong-Dallas corroboration case, passed: `2 passed`.
- A broader Windows unit run completed with `4004 passed, 3 skipped, 7 failed,
  31 errors`. The configured app and test URLs initially named nonexistent
  disposable databases. After creating and migrating only the authorized
  `gl3_coverage_followup*_test` databases, the remaining 3 cached failure nodes
  passed; the full unit suite was not rerun after migration. The root
  integration lane separately owns the full repository gate.
- Focused source-binding/verb-first suite before the final role rollback:
  `76 passed`. The final post-rollback targeted native-site regression is
  `2 passed`; no passing test is claimed for the rejected developer-role
  producer.
- The 3-case parameterized large-input test now has explicit short IDs, removing
  the Windows environment-length failure without dropping cases.
- Full CI and the full repository gate were not run.
