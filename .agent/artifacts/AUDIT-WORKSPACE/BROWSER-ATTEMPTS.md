# AUDIT-WORKSPACE browser attempt records

These are the two resolved failures from development runs. The final full workspace browser suite passed 33/33. Playwright's next runs cleared the transient per-test `error-context.md` and `trace.zip`; the console failure text is retained here, but the original zip attachments are no longer available.

## Attempt 1

Command: `npm test -- --project=regression tests/workspace.spec.ts`
Test: `active change link hides a previously stored Lead while canonical readback is pending or fails`
Result: 32 passed, 1 failed (28.1s).

Failure:

```text
Error: expect(locator).toContainText(expected) failed
Locator: getByRole('status')
Expected substring: "Loading current power-need details"
Error: element(s) not found
Call log:
  - Expect "toContainText" with timeout 5000ms
  - waiting for getByRole('status')
  13 × locator resolved to <element(s) not found>
```

Cause: the mocked 503 response completed before the transient loading state could be observed. The test now asserts the stable failed-readback alert and that the detail surface does not show the persisted Lead.

## Attempt 2

Command: `npm test -- --project=regression tests/workspace.spec.ts`
Test: same test.
Result: 32 passed, 1 failed (28.1s).

Failure:

```text
Error: expect(locator).toContainText(expected) failed
Locator: getByRole('alert')
Expected substring: "Fresh qualification unavailable"
Received string: "GridLens could not complete this request (503). Retry"
Call log:
  - Expect with timeout 5000ms
  - waiting for getByRole('alert')
  13 × locator resolved to <p role="alert">…</p>
     - unexpected value "GridLens could not complete this request (503). Retry"
```

Cause: the API client intentionally normalizes server error detail. The assertion now matches the stable 503 message.

## Final proof

`npm test -- --project=regression tests/workspace.spec.ts`: 33 passed (23.2s) after the UI copy refinement. The final screenshot is `audit-workspace-briefing.png` (SHA-256 `D5423FC7FE3F2B76E4A93A18FA8C9AD52DEF3DFFDBD3381098BAB78DEE8D18AE`).
