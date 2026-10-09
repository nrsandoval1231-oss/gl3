# A6-R2 repair attempts and retained failures

The independent R1 review receipt was preserved unchanged at
`FAILED-REVIEW.json` (SHA-256
`f7b7d27e29447e93ff1553aa52dd5ed62959aa8dff97ab6e05250a737a21c3a9`). The
source-range and false-conflict reproductions were copied byte-for-byte into
`FAILED-REPROS/`; their hashes remain `eff7d8bbf3f3938a3035e0d2e0d1a9faf05ba9be6f4f74545a19ef68fea45aa3`
and `9a59bb89327bc1243dc0cb64e6a43ea7db78680e679ae016608e1cdd274e2ac1`.

## Distinct implementation and correction

1. Before production edits, the focused unit suite reproduced the range defect:
   3 failed and 25 passed. It showed range facts rejected, the official source
   range not promoted, and suitable range arithmetic unavailable. One failure
   also exposed that the legacy zero-demand validation error no longer matched
   its existing message contract; the message was corrected without changing
   the validation rule.
2. The first interval implementation made the domain range tests green. An
   integration regression then proved a separate required projection defect:
   the 20–25 source plus accepted 22 point had a 17 MW derived gap, while
   `_effective_qualification_from_claim` still projected `required_mw` from the
   unchanged Reported source claim. The service seam now honors only the
   explicit Lead-only `fact_derived_required_mw` marker; source-only projection
   remains Reported.
3. An integration run failed because the newly added unaccepted range draft
   advanced the append-only history version but the fixture's local counter
   had not advanced. The fixture counter was corrected; no history or
   concurrency assertion was weakened.
4. A public-card test then found the derived singleton intersection gap lacked
   `remaining_mw_min/max`, so commercial-size status was `unknown`. The
   fact-assisted point intersection is now represented as an explicit
   singleton range as well as retaining its legacy scalar `remaining_mw`.
   The failed raw run is preserved.
5. Ruff's first final run found one E501 line; it was wrapped. All later focused
   checks passed.

All failed invocation bytes remain in the ignored `.artifacts/a6-r2-*.log`
files listed by `RAW-HASH-MANIFEST.json`. Their outcomes are classified there;
the three failures above are not hidden by subsequent green runs. Provider keys
were blank before each wrapper import, automation was disabled, and no
candidate `.env` was present.

## Final focused evidence

- Pytest: 50 passed, one pre-existing Starlette/httpx deprecation warning.
- Ruff: passed on both changed source files and all three focused test files.
- `mypy src`: passed on 80 source files.
- The root full backend/browser/retained-data/query-bound/migration gates and
  fresh independent Sol review remain pending on the frozen exact candidate.

No test fixture was used to assert that synthetic facts constitute real
customer evidence. No provider, original database, or retained corpus was
mutated. Model, configuration identity, and token usage are `UNKNOWN` because
they were not measured by the builder.
