# Integrated slice validation

The first ingestion slice runs locally with real public data. Controller gates passed after a bounded repair of the post-PDF lease-fencing gap. Fresh independent Sol review returned PASS for the exact candidate; the original FIX verdict is preserved. This receipt is evidence outside the implementation manifest and cannot extend review coverage to changed implementation files. Milestone A and full launch gates remain OPEN.

## Exact candidate and scope

- Repository: `gl3`, branch `build/ingestion-slice`.
- Base/local HEAD and verified remote main: `07b05b3e7de5b4a67ad9ae8aebd1cd918ba4b128`. Implementation is an uncommitted local candidate; no push, merge or deployment occurred.
- Candidate SHA256: `dc1a49e0e5e9a1d3636f3a71be8fa99ef8756dc362c32f22f7ce18990df8d072`.
- Exact disk-byte manifest: `.agent/artifacts/GL3-003/candidate_manifest.json`, 163 files. It includes application, configuration, tests and explanatory docs; mutable governance/review receipts and this report are explicitly excluded.
- Final controller validation: 2026-09-25 20:04:36–20:05:33 UTC. Raw exits/output: `.agent/artifacts/GL3-003/VALIDATION_REPAIR1.json`. Earlier failed checkpoints are retained separately.

## Working result

Open `http://127.0.0.1:5173`; the local password is in ignored `.artifacts/local-auth.txt`. Exact startup commands are in the root README and `docs/operations/local-runtime.md`. Native PostgreSQL listens on loopback port 55439, API on 8000 and React on 5173. The existing PostgreSQL service on 5432 was not modified.

| Active Signal | Original publication | Supported event / unknowns |
|---|---|---|
| Roca Honda Mine Project, New Mexico | 2026-09-14 | Proposed mine development; Federal Register JSON and matching GovInfo PDF page citation. Activity MW, start, duration and suitable supply remain unknown. |
| SteelFab manufacturing expansion, Fayetteville / Cumberland County | 2026-09-09 | NC Commerce physical expansion announcement. Construction/commissioning power is a question to investigate, not a proven supply shortfall. |
| Boat-manufacturing campus, Beaufort County | 2026-08-26 | NC Commerce announcement identifies a manufacturing campus in Chocowinity. MW, power dates and supply remain unknown. |

There are no Prospects or Leads. Two independent feeds cover three formats; the PDF is alternate evidence for the same government notice, not a third independent feed or a second opportunity.

The worker retained 92 observations and 93 evidence versions. Four project/need histories exist, of which three are active: an initial aggregate Main Street program report was rejected during controller inspection and reclassified through the corrected worker. Its source evidence and inactive history remain. Five material-history entries include that correction; they do not mean five active discoveries. The rejected checkpoint and repair are retained in `.agent/episodes/GL3-002-live-correction.md` and `.artifacts/integrated-live-ingestion.json`.

## Final gates

| Check | Exact command / evidence | Result |
|---|---|---|
| Backend lint | From backend: `uv run ruff check src tests ../scripts` | PASS |
| Backend types | From backend: `uv run mypy src` | PASS, 24 source files |
| Unit/PostgreSQL behavior | From backend: `uv run pytest tests -q` | PASS, 46 tests; one upstream TestClient deprecation warning |
| Fresh/repeated migrations and schema drift | Isolated new DB: `uv run alembic upgrade head` twice, then `uv run alembic check` | PASS; no drift |
| Frontend types/build | From web: `npm run typecheck`, `npm run build` | PASS |
| Generated contract | Root: `uv run --project backend python scripts/export_openapi.py`; web: `npm run generate:api` | PASS; complete candidate hash unchanged afterward |
| Authenticated browser/context/mobile | From web: `npm run test -- --reporter=line` | PASS, 1 live end-to-end test |
| Dependency audits | Backend: `uvx --python 3.11 pip-audit --path .venv/Lib/site-packages`; web: `npm audit --audit-level=high` | PASS, no known vulnerabilities |
| Compose preparation | Literal generated bcrypt value verified against Compose's parsed environment; `docker compose --env-file .env.compose config --quiet` | PASS, no interpolation warnings; no containers started |
| Hygiene | `git diff --check`; actual local secrets compared against manifest files without printing them; ignored paths checked | PASS, no runtime-secret matches |

Locked `uv sync --locked --extra dev` and `npm ci` passed before the final Compose/test-only repair; lockfile hashes remained unchanged. The first npm attempt hit a Windows lock on the owned Vite/esbuild process; stopping that process allowed a clean retry. The earlier Compose exit-zero warning was not accepted as success: secret quoting was repaired and the parsed hash was verified. The browser assertion was corrected to handle both JSON and PDF evidence items. See `VALIDATION_ATTEMPT_1.json` for retained failures.

## Required behavioral proof

- Real worker retrieval through PostgreSQL and authenticated presentation: `.artifacts/integrated-repaired-candidate-replay.json`, `.artifacts/final-browser-proof.json`, desktop/mobile screenshots and all three detail screenshots. No probe or synthetic record was seeded into the application.
- Identical final-candidate replay: both jobs succeeded on their first attempt; observation/evidence/project/need/change counts and Today digest stayed unchanged. Original publication dates stayed unchanged. Source health reports PDF evidence 1/1 eligible, zero deferred, with 76 non-Signal PDF representations intentionally skipped.
- Changed and returning versions, changed PDF hashes, retained prior evidence, nonmaterial revisions, interpretation failure/retry, same-content reclassification and separate similarly named sites: PostgreSQL integration tests in `backend/tests/integration/test_ingestion.py`.
- Login/malformed/empty/oversized responses and incomplete pagination: adapter unit tests. A later malformed source response preserves an already accepted observation, original date, evidence, project and active need; the worker health test separately proves the visible failure state.
- Interrupted jobs, same-session stale ownership, bounded attempts, concurrent enqueue and daily scheduler idempotence: `backend/tests/integration/test_jobs.py`. Chicago date boundary and unauthenticated private data/schema rejection: API tests plus live 401 receipts.
- Desktop/mobile browser proof covers real login, browse/detail, original dates, browser Back, restored search/focus, all source rows, and a 390-pixel viewport without overflow. All three active details were separately inspected; no browser page errors occurred.
- Local dump/restore into a new database passed with 92 observations, 93 evidence versions, four retained histories, three active needs and five events. See `docs/operations/local-recovery-proof.md` and `.artifacts/final-restore-proof.json`.

## Independent review and remaining boundaries

Independent Sol review returned FIX against the prior 515d20e6 candidate. The unchanged original verdict is `.agent/artifacts/GL3-003/REVIEW.json`. The worker now reacquires a fresh locked fence after PDF retrieval and before interpretation writes. A new two-session regression lets a replacement worker complete while the old worker waits for its PDF, then proves the old worker cannot persist stale effects. Controller final gates passed on the new manifest above. Fresh independent Sol review in `.agent/artifacts/GL3-003/REVIEW_REPAIR1.json` returned PASS at 2026-09-25 20:07:00 UTC after independently verifying every file hash and complete product-file enumeration. Acceptance covers the immediate ingestion slice only.

Docker engine execution and remote CI were not run. Compose and the suspended cloud scheduler are preparation artifacts. No cloud source check occurred while the owner's PC was off, so Milestone A remains OPEN. Full launch coverage, the 30-record review, seven daily cycles/reliability/alerts, managed recovery and Nick-reviewed real Lead evidence remain OPEN. The first-slice samples do not establish general source precision or recall.

The next milestone-ordered packet is A-cloud: provision and validate the prepared runtime/scheduler on an owner-approved host, then retain a real scheduled check with the PC off. It is blocked on explicit deployment authority and host/secret configuration. No later milestone is represented as complete.
