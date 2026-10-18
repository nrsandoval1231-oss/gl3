# Bounded receipt/note save-readback repair

Production PR80 GET is fast, but receipt/note commits invalidate saved browse and
cause 17–18s full-build pending. Audit canonical consumers before changing fences.

1. Reproduce receipt/note pending and duplicate canonical buying-chain loads.
2. Exempt only recognized commercial receipt insert/update presentation changes
   and note row DML; keep scope/identity/research/unknown-root/document/delete/
   truncate writes conservative. These are live overlays with zero saved canonical
   dependencies, so no generation refresh/revision/pointer mutation is needed.
3. Export the already computed canonical chain through an output-only call-local
   collector and reuse it in card evaluation; no injectable cache or authority.
4. Test current and prepared generations, concurrent saves during publication,
   rollback/failures, read-your-write, unknown/mixed bulk writes and qualification.
5. Run migrated-schema behavior, full regression,1×/2× histories/readback benchmarks,
   independent review and exact-head CI; guarded merge and PC-only rollout.

No UI/provider/collection/research activation, access changes, evidence deletion,
new infrastructure or canonical evaluation/ranking/grouping changes.
