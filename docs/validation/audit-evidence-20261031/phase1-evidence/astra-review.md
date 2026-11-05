# Independent Phase 1 review

Review completed: 2026-10-31T15:47:00.557249+00:00. Repository: `/workspace/gl3-phase1`; branch: `fix/phase1-reliability-20261031`; base/HEAD: `593cfd516d82a12b66558f53b975ad6c2b711517`. Reviewer did not author or modify candidate source, tests, index, or repository documentation. Only this requested review artifact was written. Review lane requested as Astra/high; no separate model-runtime attestation was available to this reviewer.

## Verdict

**No concrete correctness, maintainability, security, or authorized-scope blocker found in the staged candidate.** This is an independent source/evidence review, not formal GitHub approval, merge authorization, release acceptance, or a claim that all gates have completed.

The final strict backend gate was still running at the last evidence read (95% in pytest.log; results.json recorded only successful migration-upgrade/check). Full-gate completion and the final documentation receipt append remain pending integration work. This review does not replace that gate. No operation was denied or had an uncertain execution outcome during this review.

## Reviewed reasoning and evidence

- Read AGENTS.md and its ordered product/UI/architecture/checkpoint/finish authorities, current owner request, all 30 staged changes and the Phase 1 validation record. Authorized scope remains implementation, isolated validation, scoped publication and draft PR only. The archival documentation explicitly withdraws historical deployment permissions from current authority.
- `backend/src/gridlens/intelligence/project_results.py:95`: ordering operates on full candidate asset groups before LIMIT/OFFSET. Company/project keys use the same selected-need/rank/updated/need-ID representative order as the returned representative. Exact company-prefix removal matches `displayProjectName` including case-sensitive prefix attribution; stable asset ties and NULLS LAST are explicit. Sort is part of the cohort digest. Neither asset consolidation nor project/need identities was changed. Route validation and regenerated types agree.
- `web/src/features/workspace/CanonicalOpportunityResults.tsx:14`: cache identity, requests, URL, reload/history and pagination carry sort. Changing sort clears the cohort token and offset; server rows are no longer sorted after pagination. The footer uses server-page count for the range and separately states page-filter matches, including empty server pages. `Workspace.tsx:355` clears selection context and invalidates in-flight detail responses synchronously; explicit detail Back still uses the existing path. Both results components rewrite their browse URLs on filter changes.
- `backend/src/gridlens/intelligence/buying_chain.py:979`: joined Observation/Interpretation/Source values are passed to the existing fail-closed helper, not a new acceptance rule. Interpretation is unique per observation (`persistence/models.py:706`), so the additional source join does not multiply evidence rows. Missing binding/source, accepted version, project identity, acquisition capture and relationship rules stay in the helper; keyset paging, four accepted documents and explicit target-evidence fallback remain intact. New query-growth and binding tests cover this boundary.
- Test clocks change only test fixtures. The existing context-local evaluation clock resets on fixture exit and leaves explicit nested instants, system/lease/auth clocks and production freshness policy intact. Dallas freezes only the adapter module's test-time datetime, preserving parsing and production threshold. The recorded Dallas baseline reproduction and identical production-adapter hash support the fixture-expiry diagnosis. No shadow lock deadline or assertion is relaxed.
- `deploy/nginx.conf:7`: narrow CSP frame-ancestors and X-Frame-Options use server-level always headers, with no location-level add_header override. Existing locations therefore inherit the policy. No cache/compression, script/style/connect policy, migration, provider or production action is added.
- Dependency change is confined to pypdf 6.21.2 → 6.21.4 and matching lock metadata; dependency graph is unchanged. Inspected local audit JSON: 47 backend entries, zero vulnerabilities; npm has three moderate entries, zero high/critical. Do not imply the frontend advisory count is zero.
- Inspected final browser report JSON/log: 179 expected/pass, zero unexpected, skipped or flaky; 143.089564 seconds. Inspected mypy receipt (190 source files, no issues), isolated restore receipt (0049_scoped_identity_browse / 74 tables), backend migration exit records and test-clock reproduction. These receipts were produced by the integration work; this reviewer did not rerun full suites or touch databases. `git diff --cached --check` passed independently.

## Limits

Original one-second shadow-lock failure cause remains unproven. Reduced repeated SQL is established; a latency improvement or causal timeout fix is not. Native authenticated production timing remains zero samples. Current deployed backend/worker SHA and completed rollback state remain unknown. Local test/benchmark/restore evidence does not establish production operation or release readiness. Existing nonblocking frontend advisory debt and contained table scrolling are disclosed. Final backend result and any documentation additions must be checked before reporting an exact-candidate all-green handoff.

## Exact staged manifest

Staged binary diff SHA-256: `862a2604071ffd4a64bc3fcf6fb85c54eb5b57b2993695ea56a24bd38d319985`. All listed SHA-256 values are computed from staged blob bytes, not inferred from filenames. Code review remains applicable if only validation/checkpoint receipts are later appended and all code/test/config/dependency blobs below remain unchanged; those appended claims require their own evidence check.

| Path | Git blob | SHA-256 |
|---|---|---|
| `.agent/CURRENT_STATE.md` | `f73d41eff78a93a844744805613fdc3edb7f8542` | `14630a4999faf6a074668fa9655c1a7f1764ca647c55ae88cbb0e27590559925` |
| `.agent/OWNER_REQUEST.md` | `386d485a421cc25fb3c2a8cb404e13532a4914ab` | `0d7a0e96cc9a10453be86b6bfc4a61f93f8ce3553b51864eb896e6bdb9ccf784` |
| `.agent/WORK_GRAPH.md` | `4ad3d1c9398efd078db1802f912716d02d8cc933` | `a7c23c375b2c352d221bb76028f511b0da7b4201c96501e5d140cfd6f8f5a5a0` |
| `.agent/archive/PHASE1-20261031/PRE_PHASE1_CURRENT_STATE.md` | `301aa5a434d9be585e6f806cfa2aa7d59e42cf4e` | `4f14539432369672945ff4b3f0c9161815caa3473ba853d123f14dd6787c8533` |
| `.agent/archive/PHASE1-20261031/PRE_PHASE1_OWNER_REQUEST.md` | `b1418123486b9cdb54252bf6892f48233a866157` | `705d25d1fbf7b2f60db1abefe3fde0100294c5c28381b43a305349eb89005cce` |
| `.agent/archive/PHASE1-20261031/PRE_PHASE1_WORK_GRAPH.md` | `e7da8ac0926471f4576a5a6ed58c2f6db109d214` | `704b83fb1c5939782835ce799247ec194f7cc5f5f2a9fe037c24f71e40f58e86` |
| `.agent/archive/PHASE1-20261031/README.md` | `f5a294c5c53f0eb497cf33eb102fef40f62a63ba` | `2b2be5d94f7ce40c2609ebb0b7b7d2d9a3c500059ad765bf758e0d2d9810ec90` |
| `backend/pyproject.toml` | `051f5b1be5a6bc15532119080d218f6068c54cad` | `7f96ebacf40fd1379ac173922f16c9e73ecf7e168411f91c73b8b3265f833774` |
| `backend/src/gridlens/api/app.py` | `1599738c9cfdd719724489a103619f5f0ed28356` | `d918b2709b404141a8a36d8d39e8fe77c5e6fae96ebf71a08191428dbc937312` |
| `backend/src/gridlens/intelligence/buying_chain.py` | `2c1b908da8835611d5e62deca2c503724bdef7e1` | `666c369dd179209cbbcfa039e9b36c95cee6d423d7b8492a57a2de5cc1e567d6` |
| `backend/src/gridlens/intelligence/project_results.py` | `b6873ee717a49ced093244daf5d02a23c9a1f5c9` | `a08cbfb3026c72ca2e00ec27b6d8a9e9fcb3341e7bbd5ae1a1edbf8cbc502ce3` |
| `backend/tests/integration/test_buying_chain.py` | `287048563e57995542e5a2ab617ca72c50351bfb` | `ed7952a30b17881a149390163c04ce7af6befbb509356e69678ed62c64100872` |
| `backend/tests/integration/test_project_results.py` | `4fb137da8c7985bc9506c4b425c66270d1f84a00` | `284de0f7dd814123b7ab010b3e59b04b70d109457aa933f1efcccd25560f42da` |
| `backend/tests/integration/test_retained_evidence_loading.py` | `47cca146bb9a86e7c27ae7a2d029726d4133580a` | `221964938fec8e2b762aaafeb507adf047d05c268b16d906ff92edb53aa9356e` |
| `backend/tests/unit/test_city_permits.py` | `9d047489afb70c4308bfb6e9742a0582bb7d9233` | `c9ae9e6d80ef303e126cdf8323dc134ec666f154a2c3d28c26f33d1cda44e116` |
| `backend/tests/unit/test_deployment_security.py` | `f8dc434af47c6e5f85ea76bfa6847475bf074118` | `08c97c5b4a87263b8d99ff22eb12690b42ba5bea233a9139436c63473328036b` |
| `backend/uv.lock` | `a2f63406893bfb54015e705fec6cfb4950e3a15c` | `b62ed5c15fffe3b3e206e3e83addac75adfac6171aa06813de589a4789574bd3` |
| `deploy/README.md` | `0715d9bb7663eaf80fcaf1ab5dd24e092fb31161` | `03e25eb54d5ef7afb4cbf4d90dc966f1231ba54a751772c7236254ac0b17d9b6` |
| `deploy/nginx.conf` | `dd06aeafd55b05a6949c9ce95c3e2a96ff1f0912` | `52d038b5ef5067909d2b2b0160cad3608c534dba3c3b56a65cf0898d78806bce` |
| `docs/operations/README.md` | `dc98352450d2cf1f39f0c98de4f37becbf0f3c9c` | `6b28ff0d672a3aae6f8a20b80f409c7adc0a5b897f1cf369b005c5d0d4b8c6c0` |
| `docs/operations/local-restore-drill.md` | `b1bbb931eeef13007544015550cb135bf1b1c9d0` | `339fdbd704937161fcce317f0ebcd0a4a9eeb9e0ae9a45fcb51c76c261cb401c` |
| `docs/operations/runtime-configuration.md` | `bc2ff2341777dabae554f64c784e150c8b591038` | `9e972b9d510c69c5d995191567243c908dce80bbb47be30a466e8242518691ed` |
| `docs/operations/runtime-recovery.md` | `163a2aa7b4c07381147d89085ecf805de573ab4a` | `a1cfbaff1e29812a8bd5dc1738351e28f321e16cf3c87a3af333a17eeab1be63` |
| `docs/validation/phase1-reliability-20261031.md` | `b4e4706576e7bd2572b3d20df5af27dc53034767` | `f64c4f0345ec888213726fd5437e498526d19274ea10774aa074e1ae9b8597db` |
| `web/src/api/client.ts` | `ca6dda6a1b94b9791cbe360dfc2cb3db720b0391` | `eed77ac665b501d9b32a65b0f9010d03890df0ec687aeeb36ecbbc255447ff2a` |
| `web/src/api/generated.ts` | `abf1300561503677374ba9616d196a3d6f53feea` | `dbb1fe1faf5d6b1cc42fff45d3513017388b140f84057d6607431b1ba547dbbd` |
| `web/src/api/openapi.json` | `2be9cb21443861b23ebb39a87e2ec861ce791fa7` | `7d42c5ee8a9903f405c4dec4c1d59106c381017e3c3e64ec0f428efa94a1fbbf` |
| `web/src/features/workspace/CanonicalOpportunityResults.tsx` | `37ece37650940c8068cef3b8c25d671dcdcc18f9` | `78f2bb67f899e28164ac14ffdd9c5fccd757cc734f75bc325cd5f301e7922671` |
| `web/src/features/workspace/Workspace.tsx` | `fa1fc1c196dde0c1d1e72a8766c07e865cdc9543` | `c1f749ff0a8a8b9d9e2fdf321eb7f5c3b625c1786a691e83048b7cfe1364cdb5` |
| `web/tests/canonical_cohort_sort.spec.ts` | `5405e4625d09cc81b6084fd351869abc32fcf410` | `b37bc36dbfe45286f501a4bc2c949c959df267d858b0f1ae44745a75a8ba851e` |

## Receipt addendum — 2026-10-31T15:51:26.128314+00:00

Reviewed the subsequent staged changes to `.agent/CURRENT_STATE.md` and `docs/validation/phase1-reliability-20261031.md`. **No blockers found in this documentation delta.** The staged path set is identical to the original 30-file manifest; every non-Markdown staged SHA-256 is unchanged, as are all other Markdown blobs. No source/dependency/test/config re-review is required for this receipt-only delta.

The original review's pending backend-gate statement is now superseded: inspected `backend/pytest.log` and `backend/results.json`, confirming **3667 passed, one skipped, seven subtests passed, 11 warnings, pytest duration350.31s; process exit0 at355.946s within the480s cap**. The first strict attempt remains preserved as3666 passed/one Dallas failure/one skip/seven subtests in338.45s. Inspected format, brand and docs receipts (425 formatted files;216 assets/eight semantic AA pairs;91 maintained documents). These checks support the appended claims without erasing failed/setup attempts.

The future release compatibility paragraph accurately reflects `saved_browse._policy_fingerprint()` hashing backend Python source and selection/read fences requiring `POLICY_VERSION` compatibility. Requiring a separately authorized compatible generation/rollback path is appropriate; the paragraph does not claim or authorize a production rebuild. Production and original-timeout limitations remain explicit.

Node22 browser/type/build completion is still pending in the reviewed documentation; the Node24 receipt remains separately identified. A later completion/count/timing append needs verification against its actual receipt. No formal GitHub approval, merge, deployment, database operation or source edit was performed.

Updated documentation hashes:

| Path | Git blob | SHA-256 |
|---|---|---|
| `.agent/CURRENT_STATE.md` | `8b2a25abf55355da32b0b5128fb7eb0d929b4388` | `a65f0de850ab96aef1e0cd7cefbe0002806812530baa315653b55e886f6d2dff` |
| `docs/validation/phase1-reliability-20261031.md` | `be6247cfd40f45b396f8c9e7814395accde86142` | `3b39f198f0bcbaa6e444131797db1a3c2e7b7103c1769306f1da7aafb5140839` |

Updated staged binary diff SHA-256: `13c750a3257af811d78b89c106a2aed1d4884db1afcb6c348d8ae4155eb4b0a3`.

## Final local receipt addendum — 2026-10-31T15:53:28.171528+00:00

**No blockers found in the final receipt-only delta.** Rechecked the full staged path set and hashes against the prior review: all17 non-Markdown files are unchanged, as are all Markdown files except `.agent/CURRENT_STATE.md` and `docs/validation/phase1-reliability-20261031.md`. The changes accurately complete the Node22 receipt and distinguish local acceptance from GitHub CI and production acceptance.

Inspected `frontend/node22-version.log` (v22.23.4), `frontend/node22-results.json` (typecheck/build/browser all exit0), and `frontend/full-results.json`: **179 expected/pass, zero skipped/unexpected/flaky,144.274237s**. Browser wrapper duration146.367544s is separately recorded. `git diff --cached --check` passed. This supersedes the preceding Node22-pending statements. Backend completion remains verified in the previous addendum.

No outstanding local review blocker. GitHub CI remains a separate post-publication gate; the candidate is authorized for draft publication only. No formal GitHub approval, merge, deployment or source modification was performed. Main/remote-branch freshness was reported by the integrator and was not independently queried by this reviewer.

Final documentation hashes:

| Path | Git blob | SHA-256 |
|---|---|---|
| `.agent/CURRENT_STATE.md` | `fc03907d651af1fee7b09b61979411ff67e6ec7b` | `6e1d9ee8a2bdb3ee813141ce1f0bd4cbf9be8e0cf5b3cd5e84c71add09919a60` |
| `docs/validation/phase1-reliability-20261031.md` | `989725b7dc63b31604070146a33963674937b684` | `8f6f332e8a5ddac2b1375e5ace47bf1b8fd47fac9381eb15a3ef24901f0b02cd` |

Final reviewed staged binary diff SHA-256: `9a7bc6915e5b10f1035f61d5447735390e33d4a3e0fd70824de2b23ca7d02bd6`.
