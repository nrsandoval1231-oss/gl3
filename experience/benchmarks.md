# Benchmarks

Measured in the cloud dev container, 2026-11-06 (local disposable Postgres 16). Latest figures by the tester at end of feat/commercial-workspace-ux (earlier: web ~195 tests 1.6–2.5 min, unit 3,310, integration 1,496).

| Check | Command | Result |
|---|---|---|
| Web regression | `npx playwright test --project=regression --trace off --workers=4` | 247 tests, ~1.4 min |
| Backend unit | `pytest tests/unit -n 4` | 3,322 passed, ~29 s |
| Backend integration | `pytest tests/integration -n 4` | 1,501 passed, ~5 min 27 s |
