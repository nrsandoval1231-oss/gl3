# Soup Sieve security gate correction

November 13, 2026. Undeployed draft over audited main `bf75d32746d28ac44effcb65989d53fdeaa765e4`.

Final commercial integration CI [43343788599](https://github.com/nrsandoval1231-oss/gl3/actions/runs/43343788599) at `f6d6f563` stopped in the unchanged dependency audit before backend tests. Its retained artifact `14001225498` reports Soup Sieve 2.10 affected by [CVE-2026-126190 / GHSA-mmhr-3c5m-f64f](https://github.com/advisories/GHSA-mmhr-3c5m-f64f). This newly surfaced audit result supersedes earlier zero-vulnerability receipts; it does not establish an exploit or the deployed runtime's contents.

The advisory describes polynomial descendant-selector matching on deeply nested untrusted markup. GridLens uses BeautifulSoup selectors on fetched HTML. Upstream identifies 4.0 as fixed with caching enabled; current source does not use the unsafe `NOCACHE` fallback. No advisory exclusion, audit suppression, selector bypass or CI relaxation is introduced.

## Exact correction

- `backend/uv.lock`: Soup Sieve 2.10 to 4.0, with published wheel/sdist hashes; no other package version changes.
- `backend/pyproject.toml` and lock: Python minimum 3.11.5, retaining the `<3.12` upper bound. Installed and PyPI Soup Sieve 4.0 metadata require `>=3.11.5`; the original 3.11.0–3.11.4 promise makes a fixed lock unsatisfiable. The first resolve failed clearly for those unsupported patch versions; it was not bypassed.
- BeautifulSoup remains pinned 4.13.4; its Soup Sieve requirement admits 4.0. Local Python 3.11.16 and the preceding CI's 3.11.18 satisfy the new minimum. The existing Docker base is floating `python:3.11-slim`; actual deployed Python is unverified and must be checked before any authorized release.
- No application source, schema, identity/provenance policy, authentication or ingestion-network guard changes.

## Validation

An isolated fresh local virtual environment installed from the locked dependencies. `uv lock --check` passes. The unchanged CI audit command reports **55 audited dependencies, zero known vulnerabilities**, retained in [patched-audit.json](patched-audit.json). [before-audit.json](before-audit.json) preserves the actual failed CI evidence.

The existing ten targeted adapter/identity unit modules plus three ingestion integration modules pass: **271 passed, one existing TestClient warning in 62.27 seconds**, exit 0; [raw output](adapter-tests.txt). Tests use two fresh expressly task-owned loopback databases and existing offline/mocked source fixtures. No retained or production data, paid research, provider activation or credential change occurs. Audit/package installation queries public dependency metadata separately from application providers.

A bounded patched-library smoke checks a 200-node nested document against `section div div div` and returns zero matches without hanging. This is defensive smoke evidence, not an ingestion-performance benchmark. Independent Astra separately checks package metadata/hashes and selector compatibility; its exact report and full CI are separate receipts.

Commands, from the repository root with a disposable runtime configured:

```bash
uv sync --locked --extra dev --project backend
uv export --locked --extra dev --no-emit-project --format requirements-txt --project backend --output-file /tmp/gridlens-security-requirements.txt
uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r /tmp/gridlens-security-requirements.txt --disable-pip --no-deps --format json
uv run --project backend pytest backend/tests/unit/test_tdlr_tabs.py backend/tests/unit/test_rrc_flare_exceptions.py backend/tests/unit/test_rrc_drilling.py backend/tests/unit/test_taylor_planning.py backend/tests/unit/test_taylor_newsflash.py backend/tests/unit/test_rrc_operator_directory.py backend/tests/unit/test_ceqanet.py backend/tests/unit/test_rrc_result_identity.py backend/tests/unit/test_rrc_completion.py backend/tests/unit/test_rrc_customer_identity.py backend/tests/integration/test_taylor_ingestion.py backend/tests/integration/test_collection_only_ingestion.py backend/tests/integration/test_ingestion.py -q
```

## Release and rollback

This security patch is separately reviewable and does not accept the commercial mission, current contacts or salesperson usefulness. Earlier commercial performance measurements used Soup Sieve 2.10; they remain historical environment-bound evidence and are not relabeled as a final 4.0 performance pass. No production deployment is authorized or performed.

Keep the fixed dependency when reverting unrelated commercial code. Do not restore vulnerable 2.10 or enable `NOCACHE` on untrusted markup as a routine rollback. If compatibility prevents retaining the patch, hold release and affected untrusted-markup processing while developing a safe fix. Actual operational actions require their existing authorization; none was performed here.
