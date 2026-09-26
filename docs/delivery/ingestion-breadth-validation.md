# Local ingestion breadth validation

Accepted locally following independent Sol PASS. Candidate `6a92c9a15356e858cfd393bf6fc15ec7e30b0f18103167f06a799b8be999b0e8` covers 171 files; base `9926a9896997359d65ec7849a5969ce8f0a6109e`, branch `improve/local-ingestion-quality`. Changes remain uncommitted. No push or deployment.

Eight feeds populate 197 retained observations and 198 evidence versions. Six new publisher feeds added 105 observations. Three cannabis topic matches are visible for review. Existing three active Signals remain unchanged. All eight replay jobs succeeded; counts, Today digest, inbox digest and watch digest were unchanged.

Controller checks passed: Ruff, mypy (27 files), 62 backend tests, frontend typecheck/build, two authenticated browser tests, fresh/repeated migrations and schema drift check, diff hygiene and runtime-secret scan. API authentication, all 198 evidence rows with unique pagination, source filters, three watch matches and desktop/mobile rendering were verified. The mobile pager overlap found during visual inspection was repaired; affected frontend gates were rerun and final candidate hashes independently verified. Backend product bytes were unchanged after their passing gates.

An initial migration command omitted PYTHONPATH and was corrected. Two obsolete selectors in the temporary visual script were corrected. The builder recorded one intermittent pre-existing lease-test failure; isolated, combined and controller full-suite runs subsequently passed. One upstream test-client deprecation warning remains. Failed attempts were retained rather than erased.

Canonical evidence: `.agent/artifacts/GL3-005/candidate_manifest.json`, `VALIDATION_INITIAL.json`, `VALIDATION.json`, `UI_REPAIR.json`, `REVIEW.json`. Local runtime receipts are ignored `.artifacts/breadth-api-proof.json`, `breadth-replay.json`, `breadth-browser-proof.json` and `breadth-secret-hygiene.json`.

Limitations: latest publisher snapshots, no guaranteed catch-up after local downtime, no full-article coverage, no comprehensive state permits or official cultivation license registry. Source scope does not establish project geography. Topic matches are not qualified power opportunities. Full launch and cloud gates remain open.
