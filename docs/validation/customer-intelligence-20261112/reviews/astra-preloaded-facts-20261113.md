# Scoped ingestion-read optimization review

The first matched candidate added four SQL statements and two Project-table reads per new/changed ingestion record. `material_state` already held the Project, but its customer-fact reader loaded it again and eagerly loaded owner context even when no capacity/timeline candidates existed.

The fix passes that already-loaded Project through the existing fact reader, preserves source/evidence/hash/admission restrictions, and lazily loads a whole project-to-owner map once when candidate facts need it. Each batch row receives only its own owner context. Two defects found in review—sharing the first project's owner list and inspecting only claim quotes instead of antecedent context—were corrected before acceptance.

Independent Astra verification passed eight batch/cache/singleton/misuse controls, five payload/provenance parity cases plus a supported phase-anaphora case. PostgreSQL query compilation confirmed no singleton Project-table access while retaining source/external-ID, accepted semantic/evidence hashes, project identity and target-need restrictions. The reviewer found no remaining P1/P2 in this bounded diff. The builder separately ran 37 focused integrations; the reviewer did not rerun that database matrix.

Frozen SHA-256:

- `customer_intelligence.py`: `eb1d3340794798e4e0de18068cf4cc25143305516e85f2dbd21ad69c96f20faa`
- `change_detection.py`: `94273acccf7b9d873604fffdc5d7c1f38ae43d89bee7119a3da2557d5a1169af`
- New regression tests: `5e5341760fabd7d5c5629ea09cee5bb0030969f12a9026cd1fe8b1eff5fd9449`

Existing tests are unchanged. Matched remeasurement is a separate gate; this review does not claim performance or production readiness from unit success.
