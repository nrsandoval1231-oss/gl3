# Independent Soup Sieve security review — 46171d68

Reviewed November 13, 2026, in the assigned independent Astra critic role. Exact revision: `46171d684fc6a64d87767ce5c5ed2a07f4b0fcfa`, on the separate security branch based on main `bf75d32746d28ac44effcb65989d53fdeaa765e4`. Scope is the dependency correction and its compatibility/verification boundaries. This reviewer made no application, lockfile, test or CI edits.

**Scoped disposition: accepted as a narrow security dependency correction.** No blocking issue was identified in the inspected patch. This does not grant final integrated-candidate, commercial, performance or deployment acceptance. The full CI run after integrating this dependency remains a separate required result and is not claimed as passed here.

## Change and security findings

The commit changes exactly six files: `backend/pyproject.toml`, `backend/uv.lock` and four validation receipts. There is no application-source, schema, CI workflow, test, audit-exception, selector or network-guard change. The working tree was clean at final inspection.

The retained failed audit identifies Soup Sieve 2.10 under CVE-2026-126190 / GHSA-mmhr-3c5m-f64f. The described issue is polynomial descendant-selector matching on deeply nested attacker-influenced HTML/XML. GridLens uses BeautifulSoup's `select`/`select_one` on fetched HTML, including descendant selectors; the dependency is therefore relevant rather than an unused audit entry. This review does not establish an exploit or identify the deployed dependency version.

The lock replaces Soup Sieve 2.10 with 4.0. Independent TOML package-map comparison found no added/removed package and exactly one changed package record: Soup Sieve. PEP 440 comparison confirms `4.0` equals the advisory's `4.0.0` fixed version. Installed BeautifulSoup 4.13.4 declares `soupsieve>1.2`, which admits this version. Application source contains no `NOCACHE` flag usage; the fix's default caching is not disabled. No vulnerability exclusion, audit suppression or gate relaxation appears in the patch.

The Python requirement consistently moves from `>=3.11,<3.12` to `>=3.11.5,<3.12` in project metadata and the lock. Both installed Soup Sieve metadata and the public PyPI 4.0 metadata independently confirm `Requires-Python: >=3.11.5`. The new floor accurately drops support for Python 3.11.0–3.11.4 instead of promising an unsatisfiable dependency set. The inspected local interpreter is 3.11.16. CI selects Python 3.11; the coordinator's preceding-run receipt records 3.11.18. The Dockerfile retains `python:3.11-slim` and locked installs. Neither a floating image tag nor these source settings prove the currently deployed interpreter; that remains unverified before any separately authorized release.

## Independent checks actually performed

- Parsed old/new lockfiles and compared complete package records, confirming only Soup Sieve changed. `git diff --check` passed.
- Queried `https://pypi.org/pypi/soupsieve/4.0/json`; version and Python metadata agree with the installed distribution. Both lock artifact URLs and SHA-256 hashes exactly match public PyPI metadata: sdist `ccd6470b256394ac44b08b86fd94b30a17d335a5335c8a3d15565f7b03d3c8cf`, wheel `5e7494bfce90e06676cfb4c5c2cf22243e98e5cf24646bb1ecdda46d318550a0`. This compares registry metadata; it is not a source-code audit of the upstream distribution.
- Used the patched local interpreter to parse repository Python ASTs and compile all **62 literal `select`/`select_one` selector calls** under Soup Sieve 4.0. All compiled. This proves syntax compatibility for those literals, not complete equivalence on every source document.
- Independently ran the advisory-shaped synthetic 200-deep `<div>` document through BeautifulSoup and `section div div div`: **zero matches**, approximately **0.004 CPU seconds**. A corresponding positive nested section returned the expected identified element. These are defensive selector smoke checks, not an ingestion benchmark or an asymptotic proof.
- Inspected Docker/CI locked-install and unchanged locked-export/audit commands. No provider or source activation was needed.

The installed dependency files and checked working diff were unchanged when committed as the exact revision above. Independent execution used only synthetic markup and package metadata; it did not contact application sources or access a database.

## Inspected implementation receipts

The committed `docs/validation/security-soupsieve-20261113/` receipts retain the failed before audit, patched audit and adapter test output. The patched audit contains **55 dependencies and zero known vulnerabilities**, with Soup Sieve 4.0 explicitly present. The named ten adapter/identity unit modules and three ingestion integration modules report **271 passed, one existing TestClient deprecation warning, 62.27 seconds, exit code 0**. The coordinator records a fresh locked virtual-environment install, passing `uv lock --check`, and two disposable loopback test databases. These are inspected implementation receipts, not independent reruns of the full adapter/database matrix or dependency audit.

The previous integrated backend CI failure remains a failure: it stopped at the unchanged audit gate before tests. Earlier backend tests and zero-vulnerability receipts cannot be relabeled as a pass for this dependency set. Fresh integrated full CI is still required.

## Acceptance limits

Existing commercial benchmarks used Soup Sieve 2.10. They remain historical, environment-bound measurements and do not establish latency or ingestion-overhead acceptance for 4.0. The real 20-organization evaluation still has zero project-scoped published claims; contact acquisition, identity quality and salesperson usefulness are not established end to end. Prior unmatched before/after fixtures remain unmatched. This dependency correction does not resolve those blockers.

No production deployment, retained-data write, credential change, paid-provider execution or source activation was performed or approved. Keep the security correction independently reviewable; a rollback of unrelated commercial work must not silently restore the vulnerable dependency or enable uncached matching on untrusted input.
