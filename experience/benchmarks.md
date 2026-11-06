# Benchmarks

Measured in the cloud dev container, 2026-11-06 (local disposable Postgres 16).

| Check | Command | Result |
|---|---|---|
| Web regression | `npx playwright test --project=regression --trace off` | ~195 tests, 1.6–2.5 min |
| Backend unit | `pytest tests/unit -n 4` | 3,310 tests, ~34 s |
| Backend integration | `pytest tests/integration -n 4` | 1,496 tests, ~5 min 17 s |
