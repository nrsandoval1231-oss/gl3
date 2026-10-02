# Open PR integration validation — October 1, 2026

Owner requested validation, fixes and merge of every open PR. Inventory was #16 (`94cba4e`), #17 (`1c8be97`), and #19 (`d0e4a94`), against main `8e21750`. PR19 includes PR16; main already includes the newer UI canon from PR18.

PR17 conflicted with that canon. Its repaired head `5df22d190a481d8344255e808fb85be7df3f3cff` preserves main's AGENTS, UI_CANON and exact reference manifest byte-for-byte. The build handoff now identifies the canon as visual authority and the HTML as behavior reference, without substituting a new design or claiming UI implementation. Exact source assets remain outside the repository; obtaining those assets is still a prerequisite for visual implementation, not for this documentation merge.

All three PRs and current main were combined in isolated `gl3-pr-merge`. Existing `gl3-023` runtime, dirty recovery checkouts, databases and credentials were preserved. The acceptance database is a UTF8 clone of `gl3_027_accept`; tests use separate `gl3_merge_20261001_test`. Test model keys are blank, and automatic ingestion is off. Temporary local ports are8024/5194.

## Final local verification

- Ruff and mypy: pass, 59 Python source files checked.
- Full pytest: 559 passed, one existing skip; no tests changed or weakened.
- Frontend typecheck/build: pass; clean npm install audited 101 packages with zero reported vulnerabilities.
- Clean and repeated migrations plus Alembic drift check: pass in a fresh isolated database.
- Full browser suite: **22 passed**, with no exclusions. This includes real-data air permit, data-center enrichment, persisted pursuit notes and bounded refresh/mobile history cases previously excluded from slice-specific checks. Browser application code exactly matches the integrated candidate; only docs were merged while the run was active.
- Source replay: RRC flare retrieved38 unchanged; Boston's current bounded window retrieved9,141 unchanged, with no new or changed source records. Prior records remain retained even when they leave a rolling window.
- Replay parity: all six domain tables exactly equal. One Boston interpretation changed only its attempt count and update timestamp under its existing expired-review rule; its assessment, content hash, status and evaluator version are unchanged. Flare-only parity was exact across all seven tables.

The initial backend attempt failed the database `_test` safety-name guard and a local5173 origin expectation because of controller setup. A new correctly named isolated database and the expected local origin fixed setup; the tests and security guards were unchanged. Initial raw output remains locally in `.artifacts/pr-merge/gates-initial`; final receipts are committed under `.agent/artifacts/PR-MERGE-20261001/validation-final`.

GitHub status-check details were unavailable to the configured token. Local validation is the acceptance evidence; no hosted-CI success is claimed. Main was unprotected and both data PRs were mergeable; no protection or workflow was weakened.

Independent exact-candidate review precedes all GitHub merges. Serialized order is16,17,19, using expected head SHAs. The final remote main tree must match the reviewed integrated tree. Merge is not deployment, UI rebuild, national completeness, automatic cloud operation or parent launch acceptance.

Independent Sol review: PASS on the exact320-file manifest `7be279eb7d38d4d6738ad0667aac18debc058aa3edaa9e3fff338eba9219cbdb`. All file bytes and enumerated product paths match; the protected canonical files match current main. No material findings. Four inherited GL3-026 receipt files contain blank lines at EOF; these historical raw receipts remain unchanged and are not application defects.
