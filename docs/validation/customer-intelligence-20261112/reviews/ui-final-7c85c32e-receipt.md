# UI final verification receipt

Source/test freeze: `7c85c32e` (`Keep empty contacts out of customer cards`), included in merge `5f9a271c6ff64cd72478186ecfab76195833bb85`. No product source or test edits followed the freeze.

## Checks

- `npm run typecheck`: passed.
- Full generic regression command: `npm test -- --project=regression`; Playwright reported 338 tests. The only retained failure artifact is `auth.spec.ts`: login expected the invalid-password response but got the generic sign-in response. The captured run did not retain its final aggregate summary, so pass/flaky totals and full-run duration are unavailable and are not inferred.
- Auth diagnosis: local API returned HTTP 403 `{detail: Origin check failed}` because the proxy request Origin `http://127.0.0.1:5173` was not in `TRUSTED_ORIGINS`. No application security or auth code was changed.
- Isolated auth rerun: `npx playwright test tests/auth.spec.ts --project=regression --workers=1`; passed 1/1. Environment used `GRIDLENS_API_PORT=18001`, `GRIDLENS_WEB_PORT=15173`, `TRUSTED_ORIGINS=http://127.0.0.1:15173`, `COOKIE_SECURE=false`. Playwright reported 11.2s total (5.7s test duration).
- Moving-source affected-module run: 111 tests. Its retained failure was the desktop brand artwork pixel-height assertion (`30px` expected, `29px` received) from the pre-freeze assertion. The finalized fit/overflow assertion replaced that pixel check. A preceding parallel attempt also recorded a retry-count timing failure; the serial affected-module run passed that retry test. No aggregate moving-run summary was retained.

## Focused evidence

- Focused customer intelligence browser tests passed 3/3 before the freeze.
- The explicit null/malformed account-contact test passed with assertions that reject featured-project fallback and suppress contact-only authority, deliverability, and source metadata.
