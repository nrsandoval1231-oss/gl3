# Pursuits test race fix receipt

Commit: `81a6b9ab83bd93c1445a18359e5c4c4ddf4d71f9` on `feat/customer-first-workspace`. The commit changes only `web/tests/pursuits.spec.ts`. No application source changes; product-source freeze remains the previously reviewed UI commit. The three persisted Pursuits heading test updates are in separate commit `8da9ac87`.

## Verification

- `npm run typecheck`: passed.
- `npx playwright test tests/pursuits.spec.ts --project=regression --workers=1`: 34 passed in 43.0s.
- Test environment used `GRIDLENS_API_PORT=18001`, `GRIDLENS_WEB_PORT=15173`, `TRUSTED_ORIGINS=http://127.0.0.1:15173`, and `COOKIE_SECURE=false`; no secrets were printed.

The regression test now waits until the list and lookup requests are held, confirms “View Details” before releasing the lookup 401, verifies sign-in/session-ended behavior, then releases the stale successful list response and verifies pursuit and opportunity data remain cleared. The test retains the auth and stale-response assertions without app-source changes.
