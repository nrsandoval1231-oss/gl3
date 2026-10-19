# Editorial removal completion record

Status: implementation complete; candidate is awaiting controller PostgreSQL and
web verification. This record is not a freeze, review, merge, or deployment
authorization.

## Scope and result

Owner request at 2026-10-18 13:32:31 UTC: “I want to completely remove the
editorial part.” The candidate removes the editorial review page, menu entry,
six API routes, active domain/intelligence workflow, export CLI, feed consumer
contract, and related workflow tests/docs/settings. A legacy `?view=editorial`
URL returns to the standard private environment home.

Migration `0019_editorial_decisions`, later migration history, both historical
ORM tables and their browse-invalidation registrations remain intact. No purge,
schema migration, provider activation, publish, PR, merge, or deployment was
performed. Newsletter PRs #72/#73 remain separate and unmerged; they depend on
removed editorial helpers, and PR #72's `0020` migration conflicts with main's
existing `0020`. PR #71 is superseded.

## Candidate verification

- Unit regressions: `tests/unit/test_editorial_removal.py` — 3 passed.
- Ruff on changed backend source and tests — passed.
- Python compile check for the API module — passed.
- OpenAPI and generated TypeScript API artifacts were regenerated from this
  branch; no editorial paths or request model remain.
- `git diff --check` — clean.
- Controller reports locked local npm install/audit (0 vulnerabilities), web
  typecheck, production build, and remote full Ruff all passed.
- Isolated-schema PostgreSQL regression is in
  `tests/integration/test_editorial_removal_retention.py`. It checks anonymous and valid
  persisted-session requests, regular auth/health behavior, 404s for all six
  removed routes, and complete equality of synthetic historical decision and
  assessment rows before/after route probes. It has not run locally because no
  test PostgreSQL is available; controller verification is pending.
- Browser regression remains pending.

No live authenticated QA claim is made. Production/quality, seven-cycle, and
commercial acceptance gates remain open.

## Execution record

- Baseline: `9947b21029acacbc3cd03ed411674b86163a1baa`, schema 0024.
- Start: exact coding start was not instrumented; pre-work snapshot was created
  at 2026-10-18 13:35:14 UTC.
- Finish of this implementation pass: 2026-10-18 13:45:58 UTC.
- Model: gpt-6-luna / high (per execution assignment).
- Material repair attempts: 2 bounded fixture/test-harness repairs; no production
  API behavior changed.
- Token count and elapsed implementation duration: UNKNOWN; not instrumented.
- Candidate source identity: see `.agent/packets/remove-editorial.md` and
  `git diff` at the controller's eventual freeze. The hashes below identify the
  current generated/core files only; recompute them if any source changes.

| File | SHA-256 |
|---|---|
| `backend/src/gridlens/api/app.py` | `15bec04ac66dc78c708bcb3473bc880d6edcdd065b3d88fe29ba486e88e9d0ca` |
| `backend/src/gridlens/persistence/models.py` | `c6a8ffdaa22da606b527d1011007bfcefb4574d615aba65c19b2b043114059dd` |
| `backend/src/gridlens/settings.py` | `3be284b632f122ec8b33944287664840fc835531f44ef70af11f5f8443b322d1` |
| `backend/tests/unit/test_editorial_removal.py` | `bbac9e411b86fc3765441459eced4299cc5caca4b06724177ce20a011ab365f1` |
| `backend/tests/integration/test_editorial_removal_retention.py` | `9ccdb56f46f025aaf1b11ea4a5b30877d474cea24aec30280c79b2f50aba5edf` |
| `web/src/api/openapi.json` | `2d234551168cdbef0f12251e15ed5e722ed2a06240a7f6b3cef759dbc3c6bd41` |
| `web/src/api/generated.ts` | `8d409e10a798150f97d81700f41ef12dfd3ad6272be21c6b9b2e0441cef0e151` |
| `web/src/app/App.tsx` | `a8d7985a1d4e882126e07e287d13b3b2dd7e31cac296da0451caa8a96f46af9d` |
| `web/src/features/environment/Environment.tsx` | `97544ae774074b5a7062f73d77ba7f55123179b1da9b2eba07b9a807b3e8eff0` |
| `web/src/features/environment/environment.css` | `5cc49e6bc84044aa7497a85d779b45b0ce09fd71cf9cf5697a2d3e2158030ef5` |
| `web/tests/environment.spec.ts` | `b4c08cc3269cb3f431e760bea130ebae2a343cf4f453fbe607cf3b01019005a1` |
| `docs/delivery/milestones.md` | `da2e84ab839d5bf1f6abb725db10fc07443f33c957f984eff3da9a6f49b78a4e` |
| `docs/operations/retained-editorial-records.md` | `fac8afdfaeca21f05a958dea50617555fbd87077bfcf7c86f258739d817e071f` |
