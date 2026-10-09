# A6 buying-chain additive DTO fixture repair

This packet-only test change updates the shared API fallback in `web/tests/buying_chain.spec.ts` to return the established empty exact-Need facts page (including unavailable timing target) and `UNKNOWN` workflow-status object for those routes. The four observed failures in the root browser run came from the fallback's generic `[]` response for these newly added DTO routes. Buying-chain response fixtures, product code, and assertions are unchanged.

Root's original aggregate raw log is preserved and was not staged: `.artifacts/root-a6-ui-final-browser.log` (SHA-256 `6a8e95fef174d5115a3e991bc886ec886d2557676c9ee8491d9994210757a813`). It reports the four failures at buying_chain.spec.ts tests 46, 69, 95, and 109; each UI expectation failed after the shared fallback. Its error contexts and trace archives remain root-owned under `.artifacts/root-a6-ui-final-browser-results`.

The corrected focused suite passed all four buying-chain tests. Web typecheck and `git diff --check` passed. No product implementation was changed. Initial attempt to write a log under `web/.artifacts` failed because that directory did not exist; no raw file was created from that tool-only path error. A second Playwright launch reached backend startup but lacked synthetic database/auth configuration; that raw log is retained separately in the ignored `.artifacts` directory.

This is a builder handoff, not an acceptance verdict. Root owns the final browser/backend gates and independent review.