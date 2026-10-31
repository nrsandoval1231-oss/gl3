# Independent local recovery tooling review

Completed 2026-10-31T18:30:05.935234+00:00. Worktree `/workspace/gl3-recovery`, branch `fix/recovery-tooling-local-20261031`, base `00026c758ece2bc41eea88c478cbb0112f9e0de5`. Scope: read-only candidate review plus this requested evidence artifact only. No implementation edits, database operations, Docker/Infisical/provider execution, full test rerun, commit, push, PR or production action performed.

## Verdict

**No concrete correctness, security or authorized-scope blocker found in the reviewed local candidate.** This is source review and an inspection of focused test receipts, not approval for publication or production execution. Full strict backend validation remains pending per the integrator. Installed host tooling and current host/image/schema readiness remain unknown. The earlier one-second shadow-test failure cause remains unproven; this change does not claim to diagnose or repair it.

## Review coverage

Read current AGENTS and checkpoint/owner/finish documents. Confirmed the five previously read product, results, UI and architecture authorities are byte-identical. The latest task's local-only restriction governs over earlier stored draft-publication permission. Read the full tracked diff and both untracked candidate files, the generator and historical rehearsal entrypoints, current browse CLI, generation selection, staging/inspection/publication implementation, and affected tests/documentation.

- `scripts/stage_release_wrapper.py:135`: the four new operations map to existing CLI actions `status`, `stage-recovery`, `inspect-recovery` and `publish-recovery`. Inspection/publication accept exactly one canonical UUID; case variants, additional arguments, arbitrary suffixes and the removed rollback operation are rejected. Static operations accept no trailing arguments. Fixed Compose/Infisical/environment prefix generation, byte/AST/command identity constants, no-overwrite output handling and private file mode remain unchanged. No generic command execution avenue was introduced.
- `scripts/rehearse_release.py:733`: explicit historical acknowledgement is checked at both CLI dispatch and programmatic rehearsal entry before path, environment, Docker, output-directory or resource work. The schema0041 constants/checks and remaining guards are untouched. Current schema0049 recovery cannot be certified by this historical helper. Its old example without acknowledgement fails closed; historical release documentation is identified as obsolete by the maintained guide.
- `docs/operations/recovery-release.md`: current project/company generation dependence is consistent with the actual routes/helpers and `current_generation` predicates. `SAVED_BROWSE_ENABLED=false` is correctly rejected as a blanket recovery fallback. Policy hashing is source-bound. The guide distinguishes a documented local companion from installed host capabilities and keeps production on hold.
- Recovery order and rollback semantics match the existing guarded APIs: stage does not move pointers; publication requires the captured input/full revisions and active/prepared pointers, policy/integrity/count agreement, present validity and60s remaining, with builder serialization and a state-row lock. Candidate publication generally invalidates a prior staged receipt. Fresh staging under the actual prior artifact's policy against current canonical data is therefore required after failed candidate acceptance. Forward schema, suppression ledger, evidence and provider accounting are preserved. No old database restore, arbitrary pointer replacement or old migrate image is recommended for image rollback. `already_published` is correctly qualified by current validity/revision checks.
- Tests exercise generated suffixes through the real CLI parser/dispatcher while replacing only database functions, reject malformed/default/removed operations, assert pre-resource historical refusal, and prove the unchanged schema guard. PostgreSQL integration additions exercise stage-without-publication, pointer drift refusal, fresh stage/publication and project/company generation dependence with the switch disabled. Status dispatch is not re-executed through the real parser in the wrapper unit test; its literal suffix matches the simple existing status CLI branch by inspection and is not a blocker.

## Evidence and remaining verification

Inspected `/workspace/gl3-recovery-evidence/focused.json` and `focused.log`: all four focused modules passed **70 tests in15.78s**, wrapper process exit0 in19.3796s, with the180s cap. This was run by the integration work, not by this reviewer. `git diff --check` passed independently. No full-suite success is claimed here, and no live image-pair rehearsal is represented by unit/synthetic database tests. The actual selected prior image must support the lane and forward schema before any later authorized use; otherwise the documented outcome is a recovery hold.

No denied or uncertain operation occurred during review. No known review blocker remains; final strict tests and any subsequent file changes require evidence reconciliation before declaring the local task complete.

## Exact candidate fingerprints

Tracked `git diff HEAD --binary` SHA-256: `cfeb22123f4861db86d58cd3753e1e3502a98815fa11d7fe1c15f19465d8ea43`.

Combined candidate manifest SHA-256 (UTF-8 compact JSON, sorted keys; entries have path/sha256/bytes in path order): `aacd9f01bfd5cfa9d6fe2e58456b8d46bb318155ebc86e82e71310199aae824f`. Unlike the tracked diff alone, this includes both untracked new files. All hashes below cover current working-tree bytes, not the staging index. Artifact receipts are excluded. Only these11 nonartifact files differed from base when reviewed.

| Path | SHA-256 | Bytes |
|---|---|---:|
| `backend/tests/integration/test_browse_recovery.py` | `9e03a2b7f70d11bab7268cae031d289edd17045ea1c7cb282a011028b8b67b8b` | 19510 |
| `backend/tests/unit/test_rehearse_release_legacy.py` | `6a5a0f7428ddc9911f1c68a53ef8af19bce26129400d96153c20ef42f1dd6b0b` | 2861 |
| `backend/tests/unit/test_stage_release_wrapper.py` | `22155eab38f85411e09871cd5491377c7833216b61382ba72287a4031ddcba46` | 10788 |
| `docs/operations/README.md` | `b64536ed31f982b32dc375385abcedf2ecec67ce93bfe8a303e3c7533a7a9563` | 6718 |
| `docs/operations/contact-suppression-rollback.md` | `c4602f703f899fdafe0090e2494b23f457eadc574eefc166c666f338323a26a2` | 4134 |
| `docs/operations/local-runtime.md` | `5641bf058fa5131583dfc5036b5c7824ec67c444c07e1ba48390d66d09c1894b` | 5465 |
| `docs/operations/recovery-release.md` | `087cc860195aa9f15f11c76862880401f36621bc2183a875b90a54ec64cbcd2a` | 8953 |
| `docs/operations/saved-browse-b1.md` | `f42b8900df6a269f0841d3921932a16fc16315ca1d144a416d20713362fcdb45` | 15677 |
| `docs/operations/saved-browse-ingestion.md` | `48214bba086866cac0d24188cb5f9f1fa6dc398757f6b172a21645fe2c689cff` | 3967 |
| `scripts/rehearse_release.py` | `8ad73c82ed4ce4ff58bdd944c1973ced96a357b2c1bbf48dd4a6271da8f64820` | 41301 |
| `scripts/stage_release_wrapper.py` | `8626ca49d7d9e3c5db6f9da9e54f951bae49bee1b1170830678fd61989d9c9d5` | 7997 |
