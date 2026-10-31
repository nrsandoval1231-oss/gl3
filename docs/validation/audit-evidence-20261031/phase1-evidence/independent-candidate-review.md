# Independent Phase 1 candidate review — October 31, 2026

## Result

**No blocking source defect identified in the reviewed candidate.** This is independent source review, not a claim that the full integrated gates or production acceptance passed. The parent owns final exact-candidate full tests and publication. No PR approval, merge or deployment was performed by this reviewer.

Base: `593cfd516d82a12b66558f53b975ad6c2b711517`; worktree `/workspace/gl3-phase1`, branch `fix/phase1-reliability-20261031`. Reviewed full tracked diff and every untracked candidate source/test/doc/archive file. Read current AGENTS, owner request, product/results canon, finish contract and Phase 1 validation. Model-specific Astra identity is not claimed.

Exact path/content SHA256s, including dependency lock and final footer regression, are retained in `/workspace/phase1-evidence/independent-review-manifest.json`. Source is frozen at this review; documentation receipt additions may follow, and require a final delta read. The parent should correlate this manifest with the published commit rather than imply review of later code changes.

## Areas independently checked

1. **Whole-cohort ordering:** `intelligence/project_results.py` builds company/project sort keys before LIMIT/OFFSET from the same representative need ordering used for returned JSON. Project key removes only the exact company prefix before lowercasing, matching the visible-name contract. No returned identity/name, physical asset grouping or representative-selection rule is replaced by a frontend dedupe. Static sort mapping validates allowed modes; term/selection remain bound parameters. Nulls-last, asset-key ties and cohort-bound sort support deterministic cross-page reads. Priority/updated do not pay unnecessary ordered company/project aggregates. API literal, generated schema/types and client mode set agree.
2. **Frontend continuity:** Canonical results request actual server sort, do not re-sort the page, and key cache/request/URL state by sort. Changing sort resets offset/token and invalidates selected detail synchronously. Existing abort/generation/session-clear guards remain. Workspace detail/header navigation preserves sort. Explicit detail Back remains unchanged. The new selected-detail/history regression covers the formerly asynchronous history race.
3. **Ranges:** Loaded-page filters report visible matches independently from the server page range. I additionally flagged the existing empty server-page edge (positive total with no items at an out-of-range offset); the final delta now handles it explicitly with `0 projects on this page · N projects total` and retains Previous/Next state. A new deterministic browser regression covers that response. No inverted interval remains in this reviewed branch of the footer.
4. **Retained evidence preload:** Existing query bounds/paging/order/four-document limit remain. Observation/Interpretation/Source are passed to the existing fail-closed helper with `preloaded=True`; missing bindings still return false. Source join is outer, preserving rejection/cursor semantics. Explicit target-evidence path remains intact. Tests assert accepted evidence IDs as well as query growth and stale/rejected/missing/wrong-project behavior. No privacy, admission, retraction or provider logic is broadened.
5. **Fixture clock:** Only integration-test reads are wrapped in context-local `evaluate_at`. Production freshness policy, system time, auth/leases, explicit nested clocks, assertions and the original one-second shadow test remain unchanged. Baseline-code comparison establishes that October31 expiry existed before preload changes. Deterministic historical fixture evaluation is justified; it is not a production freshness bypass.
6. **Framing:** CSP is narrowly `frame-ancestors 'none'`, with XFO DENY, server-scope and `always`. No script/style/connect CSP restriction is introduced. Current standalone app has no legitimate embedding contract found. Reviewed actual local nginx runtime responses: static200, deep-link200, API502 and OpenAPI502 all carry both headers. Header/config tests do not certify production deployment. No cache/compression change is made without origin attribution.
7. **Operations and scope:** Maintained guides distinguish dated wrapper/recovery evidence from currently unknown backend/worker/image/rollback state. Prior instruction bytes are preserved verbatim in archive (independently compared against base blobs). Current owner/checkpoint/graph authorize only isolated Phase1 and draft publication. Company-centered hierarchy, RRC catch-up, demand/enrichment changes and production work remain deferred.
8. **Dependency patch:** `pypdf==6.21.2` changes only to6.21.4 in pyproject and lock; no new package/transitive graph expansion. The fresh initial advisory evidence had seven pypdf issues, four fixed in6.21.3 and three in6.21.4. Official release evidence records relevant security fixes. The patched current audit independently read here has47 dependencies, zero advisories and pypdf6.21.4. Full parser/regression gates still matter; advisory absence is not runtime-image certification.
9. **Performance honesty:** The synthetic2032-project/4064-need benchmark separates in-process authenticated API/SQL costs from network/rendering and real production records. Cold/warm/sample counts, response bytes and EXPLAIN receipts are explicit. Query-count reduction is not misrepresented as established wall-time improvement or proof that the original one-second failure is fixed. Public-proxy headers do not uniquely identify origin ownership. Native authenticated production timing samples remain zero.

## Verification performed by this reviewer

- Read full source/test/config/doc diff and untracked additions, including final pypdf pin/lock and empty-server-page footer delta.
- Parsed every changed Python file with `ast.parse`: PASS.
- `git diff --check`: PASS.
- Compared archived CURRENT_STATE, OWNER_REQUEST and WORK_GRAPH bytes with their base commit blobs: identical.
- Read actual local nginx response evidence and patched dependency-audit JSON (47 entries, zero vulnerabilities).
- Recorded exact file hashes in the review manifest.

No duplicate full suite, database mutation, production request, paid provider call, repository edit, commit or push was made by this reviewer. Reports/manifests were saved outside the repository under `/workspace/phase1-evidence/`.

## Remaining gates and limitations

Full integrated test/CI outcome is not inferred from prior focused passes or historical receipts. The original shadow deadline cause remains unproven even if this candidate later passes; no test deadline/assertion was relaxed. Native authenticated production performance, current deployed backend/worker revision, actual origin cache/compression policy, backup retention and final rollback state remain unverified. These limitations must stay visible in the draft PR and do not authorize production operations.

No denied action, pending approval or uncertain mutation occurred in this review lane.

## Additional test-only clock review

Independently reviewed `backend/tests/unit/test_city_permits.py` after the first full-gate attempt exposed its existing calendar-dependent failure. The same unchanged baseline adapter/test rejected the fixed August1 report on October31 because it was91days old, exceeding the production90-day acquisition window (`dallas-baseline.log`). The revised test patches only the Dallas module's datetime for this one retrieval fixture toOctober1, matching its adjacent parser fixture's explicit date. The datetime subclass retains normal construction and inherited `strptime`, so date parsing remains real. Every prior returned-ID and official-host rejection assertion remains intact. The patch is scoped/restored by pytest monkeypatch; no production adapter, acquisition bound or source data changes. Independently compared Dallas adapter bytes with base: unchanged. Read the focused result:12passed (`dallas-green.log`). This is a valid deterministic-fixture correction, not weakening the source freshness contract.

The prior reviewed source/dependency/config files were rehashed and all matched their earlier reviewed bytes. Manifest now additionally includes this one test file; exact hashes/code manifest are updated in `independent-review-manifest.json`. Original failed full-gate receipt must remain disclosed; only a subsequent complete full run can establish the gate. Final documentation receipt updates remain a separate short delta read.
