# Default customer/operator rollup — local candidate

Owner-approved scope: one default customer/operator entry with distinct projects nested under it, across Data Centers and Oil&Gas. Branch `fix/default-customer-rollup-20261031`, baseline `e0035d9e5bfb52f92bb4d21e6de0fac16d91adff`. No publication, merge, deployment, migration, retained-data cleanup/backfill or provider activation is authorized.

## Behavior and identity boundaries

Root, workspace and normal Opportunities navigation now use the existing server-grouped browse path. Search, exact stored location/event-kind filters, ranked/unranked selection, sorting, counts and pagination apply to full groups before paging. A matched group retains all its selected-sector projects. Parent/open/child tokens, cache keys and history bind the whole filter/sort context. Individual project IDs, details, evidence, contact/privacy checks and validated physical-asset rules remain authoritative. Explicit `projectBrowse=1` preserves the former flat view; historical account/group links remain supported.

Resolved groups retain regulator/company identity keys. Some official TDLR owner records have distinct project-scoped company UUIDs despite identical reported names. A separate presentation container is permitted only for exact owner-name bytes and role, frozen supported TDLR source metadata and nonempty source evidence references, without operator IDs or membership conflicts. It is labeled **Name group** and **Same source-reported name; company identities are not linked.**, with distinct identity count. This does not merge companies, pool contacts, alter suppression ownership, establish purchasing authority or create portfolio demand totals. Name variants, differing source/role, conflicts and unsupported identity cases remain separate.

## Retained snapshot probe

Read-only candidate-source projection analysis against an existing network-isolated restored snapshot returned:

| Source-supported display | Groups | Distinct physical projects | Identity state |
|---|---:|---:|---|
| AMAZON DATA SERVICES, INC / PECOS COUNTY DATA CENTER | 1 | 3 | 3 separate company UUIDs; unconfirmed name container |
| DE CENTRAL OPERATING, LLC | 1 | 48 | Resolved RRC operator102879 |
| DIAMONDBACK E&P LLC | 1 | 159 | Resolved RRC operator217012 |

All child pages were traversed and their IDs checked for uniqueness. The probe executed a read-only transaction with an explicitly selected frozen generation; it is projection analysis, not candidate runtime-policy, browser, ingestion or production acceptance. Total probe time included all parent/child requests: Amazon0.527s, DE CENTRAL7.620s, Diamondback19.279s. These are neither native rendered-page timing nor a live latency guarantee. The isolated snapshot was not rewritten.

## Validation status

Final exact-candidate full backend/browser gates and independent Astra review are being recorded locally. Initial focused runs exposed SQL alias integration errors and fixture mistakes (raw63rows include a separate conflicted project; alphabetical order; normal refetch after Back). Failures were retained rather than represented as passing. Final gate totals and reviewer outcome will be updated before handoff.

Locked frontend typecheck/build, Ruff/format, mypy, schema check and documentation links have passed at their recorded checkpoints. Node22.23.4 and Python3.11.16 are used; PostgreSQL18.6 databases are new/disposable and loopback-only. The npm high-severity audit gate passes with three pre-existing moderate development-tool advisories; dependencies are unchanged by this feature.

No production release or new live browser QA has occurred for this branch. Prior production `593cfd5` remains restored; the stale release controller was retired. Earlier unexplained480s local timeout and ingestion catch-up gaps remain unresolved limitations.
