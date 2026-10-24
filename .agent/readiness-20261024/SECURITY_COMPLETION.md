# R2 dependency security completion

Status: implementation and builder validation complete; controller acceptance remains pending.

Repository: GridLens. Branch: `audit/security-dependencies-20261024`. Base: `fae481db749b2e71dfb41ee63547c3fa1f6b1170`.

## Changes

- Updated the brand tool pins: CairoSVG 2.8.2 → 2.9.1, Pillow 11.3.0 → 13.0.0, fonttools 4.60.1 → 4.60.2, and Brotli 1.1.0 → 1.2.1. Before repair, `pip-audit` reported 79 findings in those four packages; after repair, its complete dependency resolution reported 13 packages and zero vulnerable packages.
- Added a CI audit of the full brand requirements dependency graph and retained its JSON report as a CI artifact. Existing locked-backend audit remains unchanged.
- Repair 1: the brand audit step now creates root `.artifacts/` before shell redirection. The independent review showed that the backend audit's working directory only creates `backend/.artifacts/`, so a fresh checkout would otherwise fail before running the brand audit.
- Set `persist-credentials: false` on all three checkout steps in `.github/workflows/ci.yml`, addressing the three checkout credential persistence findings reported by the controller.
- Made brand generator token and CSS text I/O explicitly UTF-8. The first Windows reproduction exposed a `UnicodeDecodeError` when reading the UTF-8 token file through the platform-default encoding; explicit UTF-8 resolves it.
- No artwork, generated public brand files, backend dependency declarations, lockfiles, or commercial logic changed.

## Evidence

Official/advisory references checked:

- Brotli advisory states that PyPI `brotli` versions before 1.2.1 are affected and 1.2.1 is patched: <https://github.com/advisories/GHSA-9v8h-qqgm-4m35>. The upstream 1.2.1 release is <https://github.com/google/brotli/releases/tag/v1.2.1>.
- Pillow 13.0.0 is published for the supported Python line and has the project release notes at <https://github.com/python-pillow/Pillow/releases/tag/13.0.0>. The installed Pillow 13.0.0 was exercised by the temporary brand generation and validation below.
- CairoSVG's 2.9.0 security release addresses recursive `<use>` rendering amplification: <https://github.com/Kozea/CairoSVG/releases/tag/2.9.0>. The additional path-complexity advisory lists 2.9.1 as patched: <https://github.com/advisories/GHSA-c3jg-qh8m-j3h2>. PyPI confirms CairoSVG 2.9.1 is published and supports Python 3.11: <https://pypi.org/project/CairoSVG/2.9.1/>.
- fontTools advisory identifies 4.60.2 as patched for CVE-2025-66034: <https://github.com/advisories/GHSA-768j-98cg-p3fv>.

## Commands and results

All commands ran in the assigned worktree. Exit codes are recorded as observed.

| Command / check | Exit | Result |
|---|---:|---|
| `uv sync --locked --extra dev` (backend) | 0 | Existing backend project and lock resolve together; pypdf is already pinned at 6.21.2. |
| `uv export --locked --extra dev --no-emit-project --format requirements-txt --output-file .artifacts/backend-requirements.txt` | 0 | Exported the locked backend audit input. |
| `uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r backend/.artifacts/backend-requirements.txt --disable-pip --no-deps --format json` | 0 | 44 locked entries audited; zero vulnerable packages. |
| `uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r tools/brand/requirements.txt --format json` | 0 | 13 resolved brand packages audited; zero vulnerable packages. |
| Temporary-root brand generation with pinned requirements and `--review-candidate` | 0 | Generated 216 assets plus manifest; approval state remained `verified`. |
| Temporary-root `tools/brand/validate.py` with pinned requirements | 0 | PASS: hashes, SVG, dimensions, alpha, names, references, fonts, tokens, and 8 semantic AA pairs. |
| Second temporary-root brand generation and SHA-256 inventory comparison | 0 | All 217 output files matched the first run byte-for-byte. |
| PyYAML parse of `.github/workflows/ci.yml` | 0 | Workflow YAML parsed successfully. |
| `git diff --check` | 0 | No whitespace errors. |
| Fresh temporary working directory: `mkdir .artifacts` then the CI brand audit command with JSON redirection | 0 | Report created; 13 packages; zero vulnerable packages. This reproduced the audit step's clean-checkout filesystem behavior. |
| `pwsh -NoProfile -File .agent/readiness-20261024/reproduce-brand-security.ps1` | 0 | Validator passed twice; 217 generated brand files and generated CSS were byte-identical across the two temporary runs. |

The reproducible helper creates a fresh unique temporary root and copies only the generator, validator, requirements, brand master, tokens, fonts, and web source inputs needed for validation. No canonical artwork or generated brand output was written by these checks. The helper's latest successful output root was `%TEMP%\gl3-brand-security-repro-b60467e9681546359319dd1df6e116a2`.

## Backend audit and remaining state

The current base already contains `pypdf==6.21.2` in `backend/pyproject.toml` and `backend/uv.lock`, and its locked audit passes. Read-only inspection of PR117 and PR118 audit worktrees found their latest commits are the same narrow pypdf change from 6.21.1 to 6.21.2 (`2f7fffb8b5befadcf289c7fe95e19af37fa56bcb` and `6b89cba66e07b09824ee3116f332151c8024d5cf`). Thus no duplicate backend lock edit was needed here. The controller reported both PR heads have since incorporated current main and are running fresh CI; their hosted results remain outside this worktree's evidence.

No web/hosted CI result, merge, deployment, production validation, or provider operation is claimed. Remaining `UNKNOWN`: hosted CI on the updated PR heads, controller exact-candidate integration/acceptance, and the parent initiative Finish Contract.

## Handoff metadata

- Repair count: two implementation repairs (explicit UTF-8 text I/O after the first isolated Windows reproduction failed; root audit output directory after independent review).
- Start UTC: `UNKNOWN` (the initial timestamp was not captured).
- Finish UTC: `2026-10-24 17:49:53 UTC` (last recorded tool timestamp; the completion file and commit followed).
- Planning/build/validation/audit durations: `UNKNOWN` (not measured independently).
- Model: GPT-6 family; exact model/config identity `UNKNOWN`.
- Token usage: `UNKNOWN`.
- Initial implementation candidate: `a33ef9bb361d6ce66fd2bf0403072242ea29d6c4`; this correction is committed separately and its exact SHA is supplied in the handoff message. This file records the exact base SHA above.
