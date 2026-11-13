# Pursuits stale-list completion test receipt

Commit: `e25fd1c7519aad0009b6b8f10fd1389d57cc956f` on `feat/customer-first-workspace`, pushed to origin. It changes only `web/tests/pursuits.spec.ts`; application source is unchanged. The prior test-only race fix is `81a6b9ab`; the three persisted Pursuits heading assertion updates are separate in `8da9ac87`.

## Verification

- `npm run typecheck`: passed.
- Focused case `npx playwright test tests/pursuits.spec.ts --project=regression --workers=1 -g 'a background 401 on the lookup'`: passed 1/1 in 2.5s.
- Full Pursuits module `npx playwright test tests/pursuits.spec.ts --project=regression --workers=1`: passed 34/34 in 46.2s.
- Test server environment used `GRIDLENS_API_PORT=18001`, `GRIDLENS_WEB_PORT=15173`, `TRUSTED_ORIGINS=http://127.0.0.1:15173`, and `COOKIE_SECURE=false`; no secrets were printed.

The test waits for the exact held list request to reach a browser terminal event (`requestfinished` or `requestfailed`), then drains two animation frames before asserting opportunity and pursuit data remain absent. Existing sign-in, auth event, URL, and private-text assertions remain.
