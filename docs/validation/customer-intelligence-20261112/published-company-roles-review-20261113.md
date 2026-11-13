# Published company roles: independent review

Date: 2026-11-13. Scope: the work-in-progress company-role path in the isolated `gl3-published-company-roles-20261113` worktree, based on the existing customer application. This is an early architecture and evidence review, not final acceptance. No source/test edits, database execution, provider calls or operational writes were performed by this reviewer.

## Initial disposition: blocked pending corrections

1. **P1 — publisher identity is not bound to the current project source.** `exact_native_company_roster_page` compares a company name with a domain label. The new discovery branch and read projection do not additionally require the actual current, hash-validated project-organization evidence publisher to match that roster host. Consequently a CyrusOne claim published by Calpine can qualify against a CyrusOne roster by name alone. The new negative test uses Calpine as the organization, which tests a different case. Require the actual current first-party source/unique company identity proof; preserve stronger regulatory domain requirements for methods.

2. **P1 — noncurrent and external people can be emitted as current roles.** Independent pure probes using `# Leadership` followed by a valid person and then `# Former Leadership` plus `John Smith\nVP Engineering` emitted John as `CURRENT`. `# Board of Directors` or `# External Contractors` followed by `John Smith, VP Engineering` also emitted John as `CURRENT`. The heading predicate accepts the former-leadership heading, and the ordinary sentence path bypasses the adjacent-roster section check. Every admitted role must be inside a positively current, company-owned roster section; a name/title alone does not resolve section ownership.

3. **P1 — cached replay can renew role age and defeat withdrawal ordering.** Discovery passes job `now` to `_store_document`, which updates an old content version's `last_seen_at`. The new projection uses that field both for its 30-day freshness window and to rank the newest source. Replaying an older retained document can therefore make an old roster appear fresh or outrank a later capture that removed a person. Use actual capture provenance and test positive A → withdrawal B → cached A replay, as well as a capture older than 30 days replayed today.

4. **P2 — the new mounted role panel has no independent expiry.** It fetches only when company ID changes. A role can cross its source-age cutoff while the parent account generation remains valid. Expose and honor the role's own validity boundary, with bounded timers; do not perform live research on navigation.

These findings were sent to the builder and coordinator before final implementation. A final review must explicitly resolve them rather than infer acceptance from the original happy-path tests.

## Evidence checked independently

The retained DataBank Markdown hash is `6adf410f7c21a766e8afd066e06f7f7f5ed79785f8e3d793bd460b37b5695e36`, matching the manifest. Publication date is unknown. The eight extracted quotes are literal source substrings under `# Leadership Team`:

| Person | Published title | Character offset |
| --- | --- | ---: |
| David Maldonado | Director, Colo Engineering | 23817 |
| Eric Swartz | VP, Operations Engineering | 24467 |
| Joe Minarik | Chief Operating Officer | 25874 |
| Tony Qorri | VP, Construction | 28461 |
| John Solensky | VP, Solutions Engineering | 28601 |
| Vlad Friedman | Chief Technology Officer | 28747 |
| Danny Allen | VP, Engineering | 30041 |
| Nick Long | SVP, Engineering, Operations and Service Delivery | 30580 |

These are company-roster assertions. This review does not verify current employment, personal contact methods, project assignments, purchasing authority, or every person in the broader research corpus.

## Architecture and validation boundaries

The intended separate role payload uses existing BuyingChainEvidence rather than a parallel persistence model. The nominal role-only discovery branch returns before writing new person BuyingChainClaims, which is the correct separation from project responsibility. The reader uses one set-wise evidence query and the existing batched buying-chain views; no per-person database lookup was found in that path.

The added alternate person-claim admission in company contact attribution and the general contact-projection label change appear unnecessary for this separate payload. New roster grammar/categories should be limited to the company-role mode unless an independently justified legacy change is required. Existing SEC method verification and unbound-team-page negatives must remain intact.

The first integration positive manually constructs its project claim/identity link and assigns a synthetic publication date. It is useful for a component contract, but does not establish the actual retained project → native extraction → canonical identity → role projection flow. A real retained-source integration is required before claiming that end-to-end result. Project claim freshness, priority, known demand and verified contact support must remain unchanged by a company-roster-only observation.

## Second implementation review: remaining blockers

The next freeze adds actual current-support publisher hosts to the reader, preserves document capture time in role evidence writes, rejects the original former/board/contractor probes, removes the alternate person-claim path, adds a bounded role-expiry timer, and seeds the positive integration through real retained DataBank ingestion and buying-chain enrichment. Those are substantive improvements. Final acceptance is still withheld for these confirmed cases:

- **P1, section ownership:** `# Leadership Alumni`, `# Leadership of Beta LLC`, and `# Not Current Leadership`, each followed by `John Smith\nVP Engineering`, still pass the DataBank roster gate and emit John as CURRENT. Prefer a finite positive heading contract rather than a substring plus an expanding exclusion list.
- **P1, whole-page withdrawal:** a newer capture containing only former leadership fails the positive roster-page check and is never persisted by discovery. The older positive source therefore remains selected. A current, identity-bound capture can withdraw all roles even when it contains no positive current-role rows.
- **P1, withdrawal across projects:** the reader ranks versions by `(project_id, url)`, although the resulting roles are company-scoped. A pure projection probe supplied two correctly hashed rows, each the latest for one current project of the same company: a November 11 roster with Joe and Jane, and the same URL's November 12 roster with only Jane. The result incorrectly retained Joe from November 11. Snapshot selection must occur for the company and source URL before extracting people, including negative captures. This probe used a fake session, not a database execution.
- **P2, unintended legacy parser change:** the original `_published_roster_title` condition is skipped when `company_only_role=False`. `John Smith, construction`, `John Smith, energy`, `John Smith, power`, and `John Smith, electrical` now emit professional claims despite failing that title predicate. Restore the existing gate in both modes.

The helper also currently permits an empty publisher-proof URL list, and discovery gathers raw historical claim citation URLs rather than the current-support URLs used by the reader. The role-only proof contract should fail closed in both paths. The new browser test should pause its clock before the first response: its five-second role lease otherwise ages during navigation before the initial visibility assertion, repeating the independently diagnosed fixture-clock problem in the main application.

## Third bounded pass

The next implementation separates negative capture admission from positive role parsing, requires nonempty current-support host proof, restores the ordinary title predicate, partitions latest captures by company source URL, and pauses the new browser fixture clock. Light independent probes confirmed all six earlier negative headings are withheld while still admissible as negative captures, and all four unintended legacy title admissions are closed. No database, browser or full typecheck was run in this pass.

One concrete section-ownership defect remains: `# Former Leadership\n## Leadership Team\nJohn Smith\nVP Engineering`, `# External Contractors\n## Management Team\nJohn Smith\nVP Engineering`, and `# Beta LLC\n## Leadership Team\nJohn Smith\nVP Engineering` still emit John as CURRENT for DataBank. The nearest-heading lookup discards adverse or foreign parent headings. Heading ancestry or a bounded top-level roster contract must preserve that ownership context.

The source version selector also needs an explicit conflict control: two different hashes at the same latest capture timestamp cannot be ordered by a random evidence UUID. A positive/withdrawn tie should abstain; identical-hash copies across projects may be collapsed. Final acceptance remains pending those controls and the final frozen hashes.

## Source-bound light disposition

The latest implementation closes the reported source-level defects. Only a finite positive H1 roster section admits rows; nested headings disable it. The separate same-publisher capture gate preserves negative snapshots. The company-wide URL selector uses `dense_rank` on `last_seen_at` alone, keeps all latest evidence reasons for conflicting-hash comparison, and only then selects role-only evidence for extraction. An immutable first-observed date and random UUID no longer break a latest-capture tie.

**25 independent light controls passed**: the six earlier flat-heading negatives and their retained negative captures; three nested adverse/foreign headings; four restored legacy title controls; direct execution of the new saved pure test function; all eight verbatim DataBank roles; missing/wrong host-proof refusal; SQL window/filter shape; cross-project withdrawal; whole-roster withdrawal; old-A recapture tied with withdrawn B; a tie involving another evidence reason; identical-hash duplicates; and old, future or hash-tampered source refusal. The projection controls supplied the expected window-selected rows through a fake session and inspected the constructed SQL. They are not PostgreSQL execution. No database, browser, provider or full typecheck was run in this pass.

No remaining material blocker was confirmed in this bounded read/pure pass at these SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/src/gridlens/intelligence/buying_chain_extraction.py` | `dd99a8929a9fb0732baca562a59fda4b7382ca843af535bbee21dc3bb92cfea0` |
| `backend/src/gridlens/intelligence/company_contact_discovery.py` | `9c519191e9b2044fff98bf2e8ae7f6e6fc0991ccc47c2c41254d774c1f52b425` |
| `backend/src/gridlens/intelligence/company_contacts.py` | `61ffba9c1d9f6c873d0feba211923348ade65600dacbb3378931415b81704f3b` |
| `backend/tests/integration/test_published_company_roles.py` | `caffe26b516bc02a4915baed2fb8440cb9ab86186e8568d076aa4fa751f4dcff` |
| `web/src/features/workspace/CompanyContacts.tsx` | `0d2b625541be62fc002a9c2a27058f3d596f32725fee5e71cd2dbc0826d8509f` |
| `web/src/features/companies/CompanyView.tsx` | `4d7ee2d7bc9a7f4b66483800d3e12447e04bac5d9693e81a7053ed0a5cb8ddc4` |
| `web/src/api/generated.ts` | `c7312533efb49fecfd515139a9c8129d1428d57724c773c4628b63c0779434c3` |
| `web/src/api/openapi.json` | `7e7464f84a86f69cddff824a54cbb2a9227bce40cefb63226df2c61a9340ae5d` |
| `web/tests/published_company_roles.spec.ts` | `5d3f15cc429a143e755d54ca98ae410b56becec8ef3ed1db2ba76fb71edb28ce` |

The final PostgreSQL integration run, unchanged contact-attribution regressions, generated contract/type checks and mounted browser expiry test remain pending until the coordinator clears the shared test lane. Earlier builder passes predate these last corrections and do not prove this snapshot. The mixed-reason tie was independently exercised but should also receive a saved new regression control. This disposition does not establish verified employment, contact methods, project assignments, engineering demand, production state or complete commercial acceptance.

## Final bounded acceptance — e41eca71

**Accepted for the reviewed company-role scope at commit `e41eca7169ce7879c6911487bd7a4ce07c4c978e`.** No remaining P1/P2 was confirmed in the final independent source/test read. This supersedes the pending disposition above, while preserving the historical findings and their closure evidence.

The final mixed-reason regression is effective: after the role-only tie control, a fresh day-two positive capture first makes Joe visible; a competing ordinary-contact-source hash at the same URL and capture time then withholds all roles. The test no longer passes merely because two older role-only hashes already conflict. Actual retained DataBank ingestion and enrichment create the canonical anchor; the positive test preserves its September 10, 2024 project publication date and existing buying-chain run, creates no person project claims, and returns eight company-only role assertions with unknown project relationship, no methods and no project IDs.

The final reader adds one set-wise Project lookup so the shared extractor receives its existing typed project argument. It adds no per-person query or live research request. The new UI UUID guard prevents malformed/noncanonical IDs from triggering the UUID endpoint; valid canonical UUIDs still fetch normally, and prior requests retain abort cleanup. The only related fixture-ID adjustment is in the new role test. Its clock is paused and it checks removal at the independent five-second role lease.

Final inspected SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/src/gridlens/intelligence/buying_chain_extraction.py` | `7f313c3c0dfefa1373320e5991dcc679985808f4099c8feecccd9d716ae18724` |
| `backend/src/gridlens/intelligence/company_contact_discovery.py` | `f1c1cade9602361631962b8dcc2feb8ff512ef62e329dc4f317b2df68fa71c3f` |
| `backend/src/gridlens/intelligence/company_contacts.py` | `1ab202a9953157e51e506f969a5596aa089ebb291681d40adb9cebec141330b5` |
| `backend/tests/integration/test_published_company_roles.py` | `878f97f8aad6bf6eda1f237014193252b91c3c4467ee2cc677bad3ca9ddfb4a1` |
| `web/src/features/workspace/CompanyContacts.tsx` | `fff95d13dfaef869f5e7baef145c51f2bf39d1f2918039724a8dbcb943309e41` |
| `web/src/features/companies/CompanyView.tsx` | `4d7ee2d7bc9a7f4b66483800d3e12447e04bac5d9693e81a7053ed0a5cb8ddc4` |
| `web/src/api/generated.ts` | `c7312533efb49fecfd515139a9c8129d1428d57724c773c4628b63c0779434c3` |
| `web/src/api/openapi.json` | `7e7464f84a86f69cddff824a54cbb2a9227bce40cefb63226df2c61a9340ae5d` |
| `web/tests/published_company_roles.spec.ts` | `68ab1b2a4e8904a588b5b59ebb5fc151402268542eac5056a39558b59faf5a89` |

The coordinator confirms the builder's final gates: 23 role/privacy backend controls passed in 53.57 seconds in an isolated loopback test database; 34 targeted browser checks, including mounted role expiry, passed in 43.7 seconds; TypeScript checking, production build, mypy over 276 files, Ruff check/format and documentation graph validation passed. The build retains its 553-KB JavaScript bundle advisory. These runs were not independently repeated by this reviewer. An earlier browser failure caused by a malformed synthetic account ID preceded the UUID guard and final passing run.

This accepts published, source-cited company-role information with its stated limits. It does not verify current employment, personal methods, buying authority or project assignments; establish four or twenty commercially usable accounts; remove regional/Need restrictions; authorize deployment or operational writes; or declare the broader commercial mission complete.
