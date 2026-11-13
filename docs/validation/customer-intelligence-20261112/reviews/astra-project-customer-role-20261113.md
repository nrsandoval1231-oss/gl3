# Scoped project-customer role review — November 13, 2026

Independent Astra review found no material defect in the additive enum/order, producer role filters, sector selection, preferred-role retractions, search and grouped rollup changes. This closes the earlier producer allowlist omission and retraction fallback findings. It does not accept the real-source extraction path or overall commercial usefulness.

Data centers prefer owners, explicit project customers, then operators. Oil and gas keeps its existing preference and excludes project-customer retractions from its owner/operator fallback block. Unknown-sector conflicting identities stay unresolved. Account producers derive the complete role set centrally; the documented historical four-role export remains a compatibility subset. Existing test files are unchanged.

The builder ran 33 focused PostgreSQL/unit checks across eight modules: new selector and source-path controls, projection/collision/retraction cases, and existing primary-role, identity, query-budget and scale guards. All passed in 133.48 seconds with two existing deprecation warnings. Astra independently ran four pure unit controls in 0.42 seconds; an earlier unconfigured attempt produced settings errors and is not a passing result. The reviewer inspected but did not rerun the PostgreSQL matrix.

Reviewed source SHA-256:

- `domain/buying_chain.py`: `69a1fef40223ada79a2bf78f35e39a6f636720ab16732d04530cb77271f16a64`
- `intelligence/customer_primary.py`: `b188634d19e620ec40b5a639c6dd7992977c5847376f3dafc8a3ad23cf77eb47`
- `intelligence/customer_accounts.py`: `de0163ba759d2a7c29d361b6f707e6d5fd167a5f5b0ce34fc0caaa33934807b6`
- `intelligence/customer_results.py`: `291705e6cc9b0c9e200e7782084571e5302b3975da87d0ff1e7148c992a918af`

The results file has separately reviewed card-target edits. This role disposition applies only to its role/search/rollup hunks, and is not acceptance of unrelated code. Full-suite checks, matched performance measurements and integrated source acceptance remain separate gates.
