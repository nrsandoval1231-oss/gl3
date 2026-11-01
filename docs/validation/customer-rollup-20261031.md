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

All child pages were traversed and their IDs checked for uniqueness. The probe executed a read-only transaction with an explicitly selected frozen generation; it is projection analysis, not candidate runtime-policy, browser, ingestion or production acceptance. Total probe time included all parent/child requests: Amazon0.618s, DE CENTRAL15.296s, Diamondback36.668s. These are neither native rendered-page timing nor a live latency guarantee. The isolated snapshot was not rewritten. DE CENTRAL company membership was checked; a separate STORMCHASER title-specific assertion was not captured. The accepted module byte hash is `7ed484698789ac1ced9ce371e7ab6c15765857b6d276748b2c0daf38d8fcb773` (Windows checkout); its canonical Git LF hash is `f11a0614294a45accb986fe082cf6ee40169fda213d006d7cf0e8e71117ee80e`.

## Validation status

Product source was independently reviewed at `70c964608d3c1385f2289df1e8a7b36c985e6b29`. Exact backend validation candidate `d30f9e35951a9288c642fce1fd3f6c78b9e98568` adds only a deterministic test-clock fixture, with every original assertion retained. The 2,141-file canonical source archive was checked against Git blobs; SHA256 `15cfc7e65830688d306e5351b7262df225b22beedd2230cce26f51cd59a495d6`. The archive uses canonical LF bytes without changing persistent Git settings.

| Gate | Result |
|---|---|
| Full backend, Python3.11.17 / PostgreSQL18.6, four workers, 480s bound | 3,695 passed, 2 skipped, 7 subtests; 196.53s (wrapper198.91s), no timeout |
| Focused grouped API/search/identity/query-budget integration | 25 passed, 31.30s |
| Deterministic publication fixture, both parameters | 2 passed, 3.98s |
| Full browser regression, verified Node22.23.4 | 184 passed, 1.5m |
| Additional same-name group/detail/Back on phone390x844 | 1 passed, 6.2s; captured frame visually inspected |
| Native Docker Compose contract | 1 passed, 1.10s |
| Ruff / format / mypy | Passed; 426 formatted files, 190 typed source files |
| Schema compatibility | Alembic check: no new upgrade operations, schema0049 |
| Frontend typecheck and production build | Passed; frontend unchanged since full browser gate |
| Locked dependency audits | pip-audit: no known vulnerabilities; npm high-severity gate passed, three existing moderate dev-tool advisories |
| Independent Astra/high review | PASS: exact d30f9e3 local implementation/validation, no blocking findings |

The Linux image lacks the Docker Compose executable, so that case is covered by the native one-test gate; the other declared backend skip is an explicitly optional live NC Commerce probe. Browser coverage includes actual local authentication/expiry, default navigation, full-cohort grouping/filter/sort/pagination, expansion, loading/error/503/cohort reset, details/Back and desktop/phone layouts. Retained snapshot projection is separate from these synthetic local browser tests.

Failure history is retained. Initial integration and identity/UI review findings were corrected, not hidden. Native Windows full backend validation exceeded480s for an unexplained reason. A Linux attempt correctly failed the nonloopback database guard; it also exposed CRLF shell bytes from the Windows archive. These were corrected through genuine loopback topology and a byte-verified canonical archive, with no guard weakening. The next full run produced3,694pass/1fail/2skip: a pre-existing fixture crossed the UTC midnight preparation window. Freezing its controlled clock at noon before initial generation construction fixes the fixture; application behavior and assertions are unchanged. The final post-fix full run passed3,695 tests plus7subtests with2declared skips in196.53s (wrapper198.91s), without timeout.

Logs and receipts are in `.agent/artifacts/CUSTOMER-ROLLUP-20261031/`. Historical builder receipts describe their own checkpoints and are superseded only by the final controller completion and independent review receipts.

No production release or new live browser QA has occurred for this branch. Prior production `593cfd5` remains restored; the stale release controller was retired. Earlier unexplained480s local timeout and ingestion catch-up gaps remain unresolved limitations.
