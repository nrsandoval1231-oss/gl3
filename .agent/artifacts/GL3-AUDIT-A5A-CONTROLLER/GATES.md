# A5A root deterministic gates

Status: VALIDATION PASS, independent review PENDING. Source candidate067d5d6e9f76c03954b0d6242b9efd87c4453f5c/tree92eef5b352c363f8fb56a07de250c4decdbc3527; accepted baseline5c03880584f6aacae95a81ab2231a80e63503cc8. Root proof adds only controller documentation/artifacts before review; product/test/workflow inputs must remain byte-identical to this tested source.

| Gate | Result | Raw receipt inside ROOT-RAW.zip |
|---|---|---|
| Locked Python3.11 backend |1345 passed,2 skipped,5 warnings,208.14s|root-a5-r1-final-full.log|
| Repository Ruff and new benchmark scripts |PASS|root-a5-r1-final-ruff.log;root-a5-r1-benchmark-script-ruff.log|
| mypy |77 source files PASS,2 existing unchecked-function notes|root-a5-r1-final-mypy.log|
| Web typecheck/build |PASS|root-a5-r1-final-web-typecheck.log;root-a5-r1-final-web-build.log|
| Locked backend audit |44 dependencies,0 known vulnerabilities|root-a5-r1-final-backend-audit.json|
| Web audit |0 vulnerabilities|root-a5-r1-final-web-audit.log|
| OpenAPI |Exact unchanged committed contract match|root-a5-r1-contract.log|
| Fresh0016/repeated migration/drift |PASS on newly empty gl3audit_a5_final_migration|root-a5-final-dbprep.log;root-a5-r1-migrations.log|
| Fresh browser regression |36 passed,37.4s,ports55513/55514 subsequently closed|root-a5-r1-final-browser.log|
| Original corpus columns |24 table fingerprints unchanged against post-recovery snapshot|root-a5-r1-corpus-preservation.json|
| Known task secrets/fragments |0 hits after explicit diagnostic redactions; includes private test password|root-a5-r1-final-secrets.json|

The two skips are Windows symlink privilege unavailable and optional local NC article access probe absent; see root-a5-r1-skip-details.log. Warnings are existing Starlette test-client, Alembic path-separator and websockets deprecations, not omitted acceptance failures.

## Frozen corpus comparison

READONLY gl3audit_a5_corpus_test, governed comparison date2026-10-07. Full semantic oracle SHA85e3d525b199bcb42f65e8fd6e10cf0e2be08bd9673e3a6cb23930a8b6352bab; selected card SHA4d44821139abdd92a657aa7f419f86754abb33be0e1e0d5082278dee0bed4812. Exact eligibility, priorities, work identity, grouping and full selected detail PASS.1167 eligible Signals/1144 groups; first50 groups contain53 needs,202084 serialized card bytes.

| Matched read | Accepted baseline | Root candidate |
|---|---|---|
| First process read SQL |5731|67|
| First process elapsed |13.930833099992014s|5.53331129997969s|
| First process peak Python allocations |56227663B|7977267B|
| Warm same-process elapsed |14.323216999997385s|5.13888790004421s|
| Warm peak Python allocations |54001505B|7874992B|
| Serialized card bytes |202084|202084|

First-process measurements do not control disk/database cache; Python allocations are not process RSS or a production SLO. Root benchmark ran after full tests ended. Raw root-a5-r1-retained-benchmark.json/log preserve exact measures.

Summary diagnostics: candidate batch128; resident linked ORM381<=384; lifecycle ORM424<=512;938 lifecycle rows streamed/929 canonically supported;0 historical Evidence ORM/0 brief ORM in summary. Original retained dates are SQL aggregated. Full suite includes130-candidate/261-link and261-supported-event stress, batch-crossing siblings, preloaded-session preservation, typed consistent Lead and mixed typed-conflict/legacy Prospect nonpromotion. No synthetic fixture is an actual customer confirmation or real Lead.

## Failures and provenance

Initial frozen cb6138e full run:4 failed/1341 passed/2 skips/5 warnings196.61s; RuffI001. Three auth failures were root harness's empty disposable application database, corrected by migration only; the exact original three tests subsequently passed in root-a5-r1-original-auth-failures.log. Remaining fixture mocked obsolete single-chain helper; R1 changed only that batch mock and export-test import order, preserving assertions. Initial failed receipts remain archived; no auth/product repair was hidden.

Earlier boundedness1234/387 failures, fixture corrections, typed qualification version-loss regression and prior slower/higher-memory experiments remain historical evidence. One console log was overwritten across failed invocations: original failed bytes/hashes are UNKNOWN and reconstructed text is explicitly not original raw. Credential protection overrides retaining secret-bearing diagnostics: worker removed one local error log with a redacted receipt; root found two additional ignored logs, retained original SHA hashes plus redacted copies, and removed their secret-bearing originals. Old manifests remain historical hash receipts, not proof that those excluded raw bytes are available. See root-a5-r1-diagnostic-redactions.json and worker overwrite/configuration incident logs. New Git commit blobs had no known task-secret matches. No secret values are in these receipts.

Archive3b9d4f5d58a15ad379fec28b2cfa0b7b52c013e5d6ebd093409db2c64accba33 has89 byte/hash-verified entries. Original backup SHA828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886 remains unchanged. Raw historical whitespace is immutable; source/docs/packet diff checks are scoped separately.

## Scope and remaining work

A5A bounds unselected summary ORM/history and hydrates only selected group members. Selected complete-group detail still depends on member cardinality;53 members in this corpus is a measurement, not a universal50-record ceiling. Public pagination/search/filter/group-completeness/history/client/export remains A5B and is not certified here. A6 attributed facts and A8 inert readiness/recovery tooling remain pending. Launch configuration must prevent credential-bearing validation diagnostics as part of operational preparation. A7 still needs original checksum-matching PNG/HTML; supplemental video cannot substitute. No original-data mutation, provider activation, GitHub merge, deployment or operational/real-Lead acceptance occurred. Parent OPEN.
