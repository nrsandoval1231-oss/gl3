# Aligned and Switch native-source coverage review — November 13, 2026

Status: bounded source-admission change accepted at the final hashes below. The initial confirmed defects are retained as review history and have been closed by independently verified repairs. This review is isolated to `/workspace/gl3-native-source-coverage-20261113`, based on `2336b02a`. It does not change or accept the main application UI, production state, commercial coverage, or customer-card count.

Initial reviewed SHA-256 values:

- `backend/src/gridlens/ingestion/adapters/retained_company_projects.py`: `d54461451c3503482b65f43f2dd189fa790dfa0394393db1e2e92d0a1b3542bc`
- `backend/src/gridlens/domain/project_activity_binding.py`: `6cbe312d432f815d0a4d3cfc0b586effe167081c9544de2fae76b474617e9937`

## Initial confirmed defects — repaired

The following pure probes ran against the initial hashes, without database or provider calls. Findings were sent to the extraction builder and coordinator before any repair.

1. **P1 — admitted campus aliases bypass cancellation.** Appending any of `The Rock has been canceled.`, `The Rock campus has been canceled.` or `The Fifth Prime campus has been canceled.` to the actual Switch excerpts still returned `CANDIDATE`. The adverse-status gate at initial lines 1095–1120 checks the full primary project quote and locality, but does not recognize the newly admitted literal alias or its explicit short campus name. A current negative source must not be admitted merely because its status uses the source's own alternate site name.
2. **P1 — announcement and construction referents are insufficiently bound.** The new helper at initial lines 927–959 accepts a negated announcement and construction explicitly assigned to a separate campus. The generic reproduction below remains `CANDIDATE` when `Acme announced` becomes `Acme has not announced`, or when the construction sentence starts `For a separate campus, the land agreement...`. A same-paragraph actor mention does not establish that this physical construction object is the announced campus.
3. **P1 — paragraph separator bypass.** The new paragraph expression at initial line 911, repeated in alias extraction, rejects a clean LF-LF boundary but crosses the boundary when preceded by one/two trailing spaces or encoded CRLF-CRLF. Those are normal retained-text/Markdown forms. The announcement can therefore be in one paragraph and construction/alias in another despite the helper's stated bounded contract. Source offsets must remain exact while recognizing these boundaries.

Generic reproduction:

> Acme announced the primary location of its Alpha data center campus in Texas. The land agreement will allow Acme to construct new data center space next to Acme headquarters in Round Rock, Texas. The Alpha campus will be called “Alpha One”.

The clean form is a positive control. `Alpha One has been canceled.` appended in the same or next retained section also reproduces blocker 1. A negated action (`will not allow`) and sibling rename (`The Alpha East campus`) correctly return HOLD.

The first repair (`88dfd682…`) closed the initial prefix examples but still admitted the following variants of its narrower positive, using `The land purchase agreement with Acme will allow Acme...`: an intervening `A separate campus is planned in Round Rock.` or `The following agreement concerns a different site.` sentence; a construction actor Beta mentioned only as Acme's competitor; a negated rename (`It is not true that the Alpha campus will be called…`); and the same literal alias separately assigned to Beta or Alpha East campus. These were reported as remaining P1 referent/alias boundaries, not additional feature requirements.

A cross-section control demonstrated the material consequence: actual Switch excerpts plus `The Beta campus will be called “The Rock”. The Rock has 500 MW of IT load.` admitted the native alias and the existing customer scoper attributed 500 MW to Fifth Prime. The final source-wide alias-conflict check rejects that input before it can supply project aliases.

**P2 — negative receipt loses its supporting quote.** After alias-aware cancellation began returning HOLD, a temporary copy of actual Switch with `The Rock campus has been canceled.` appended produced an `adverse_status_review` record whose `status_quote` was empty. The receipt selector still required locality text, while the updated admission gate recognized the native alias. The identity-history guard rejects an empty quote, so no identity promotion bypass was demonstrated. The exact negative source clause must nevertheless survive in its receipt. Only the temporary fixture's source hash manifest was recomputed; original retained sources were unchanged.

## Confirmed safeguards and scope limits

The unchanged retained corpus produces four native records and eighteen holds in this candidate. The native interpreter reparses all four. Aligned remains located only at `Conesville Industrial Park`, without an inferred state; its publication date is `2025-07-24`. Switch is located at `Round Rock, TX`; its metadata publication date remains the historical `2021-06-01`. The existing DataBank and Cyrus dates remain `2024-09-10` and `2025-07-30` respectively.

A separate subprocess comparison against the unchanged main adapter confirmed the complete existing DataBank and Cyrus record dictionaries are identical, including source hashes `baf748307ce3f3642eef04fc21dd22f6a4f378baf5e0f9ca9707abc27a6bc7af` and `f00a099095c2ac1fb66c38be615dcd756b962efa7fff3a85008097e51f47b332`. The selected pure coverage/activity/publication-date suite passed 28 tests. Its first attempted invocation stopped in the required-settings fixture; the successful invocation supplied dummy settings and an unreachable loopback database URL, with no database test or xdist worker.

Independent execution of the existing customer scoper over actual Switch text produced no capacity or timeline claims. Adding Dell-headquarters 500 MW, adjacent Beta Campus 700 MW, or Austin/Houston ecosystem 185 MW examples caused raw electrical claims to be extracted but all were excluded from the selected campus's scoped claims. These checks support quantity isolation; they do not cure the source-admission blockers above.

The new regional integration test was read, not rerun by this reviewer: it requires an Aligned Project with unknown/noneligible region and no PowerNeed, while Switch is region-eligible. Four source admissions do not establish four customer accounts, four Needs, verified contacts, commissioning demand, or current construction. Applied remains held. No gold references, retained public-source files, original tests or production data were changed by this reviewer.

## Final disposition and verification

No remaining material blocker was found in this bounded implementation at these SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/src/gridlens/ingestion/adapters/retained_company_projects.py` | `206be09af11d906ebffc3e05b28bb4b486b9dd819a2be12f6c8a6bd4d201d9a9` |
| `backend/src/gridlens/domain/project_activity_binding.py` | `6cbe312d432f815d0a4d3cfc0b586effe167081c9544de2fae76b474617e9937` |
| `backend/tests/unit/test_retained_native_source_coverage.py` | `91c937f47838ad80222b426445d8e5393a42e45f6dc4958a4f2289631fe2aa8b` |
| `backend/tests/integration/test_retained_native_source_region_guard.py` | `5e5e013f0fb377c25208cb2a6355941799ed1b7e12f2943e364ce7c82fa98d6a` |

The final Switch path requires an explicit source-defined actor alias, an immediately consecutive announcement/construction/naming sequence, the same exact actor in the construction clause, and a same-paragraph literal site name. Paragraph ranges preserve offsets across LF, CRLF and trailing-space forms. Alias conflicts are checked across the retained sections, and adverse detection returns the exact source-local sentence used in the negative receipt. Aligned's change selects the actual park-location suffix span without inventing geography. These changes remain within the existing inactive offline adapter and activity-binding helper; no provider fetch, model, identity merge or alternative ingestion pipeline was introduced.

Independent verification at the final adapter hash:

- **49 pure controls passed:** clean generic and actual positives; all reported announcement/action/naming negatives; five paragraph separators; alias and short-name cancellation in the same/next section; same- and cross-section alias collisions; source-hash-bound native reparsing and exact spans for all four rows; identical repeated retained replay; tampered alias rejection; exact negative receipt quotes; and foreign 500/700/185-MW quantities withheld from the Switch project.
- **33 selected tests passed** with `PYTHONPATH=backend/src /workspace/gl3-commercial/backend/.venv/bin/python -m pytest backend/tests/unit/test_retained_native_source_coverage.py backend/tests/unit/test_project_activity_binding.py backend/tests/unit/test_retained_publication_date_boundary.py -q -o addopts='' --tb=short`. Required settings were dummy values, including an unreachable loopback database URL; no database fixtures or xdist workers ran.
- The new saved controls use the supported quote-defined actor/land-purchase positive frame before introducing their adverse variation. Existing tests were not rewritten to accommodate the parser. The builder additionally reported a 52-test focused suite and targeted Ruff checks passing; the reviewer did not independently rerun that broader selection or the regional database integration.

This accepts the source-bound coverage repair for further integration review. It does not approve merging, deployment, source activation, retained operational writes, regional eligibility expansion, customer-card publication, or claims that the historical announcements establish current commercial demand.

## Planned-developer producer addendum

The additional Switch producer has no confirmed material blocker at the following reviewed hashes:

| File | SHA-256 |
| --- | --- |
| `backend/src/gridlens/intelligence/retained_project_organizations.py` | `16d791bc5735fd24a3db82edf77727a38943c69575337cbc8579a3a26aaba5c1` |
| `backend/tests/unit/test_retained_native_planned_developer.py` | `9d6e8e6973310849bc862a6a0e6da6a62f28ef2934fdf388b6c1430c1b90e788` |
| `backend/tests/integration/test_retained_switch_planned_developer.py` | `c10e811ad4a33a80f6af13803cddbf4190c8bf9163976587dba735954eb9c871` |
| `backend/src/gridlens/ingestion/adapters/retained_company_projects.py` | `ece4be5b9b1f1e214b98834af2ec000dc2fea6acf072636b1511bcc8fb19dd62` |

The last adapter hash includes two additional conservative guards inspected during this review: a missing `space` match returns no candidate, and selected spans are validated and normalized before comparison. The activity helper remains at the earlier accepted hash.

The producer runs only after the existing retained source/document/observation/evidence/interpretation/project agreement and native reparse checks. It requires a publisher-host link naming the actor, a source-defined actor alias, and the same actor's explicit planned construction immediately following the selected campus announcement and preceding its native literal alias. The ordinary `Extracted` result records a source-reported planned developer; it creates no global company identity and explicitly does not establish legal ownership, completed construction, current status or purchasing authority. Citation quotes are verbatim. Historical publication dates remain historical.

Independent verification used dummy settings and an unreachable loopback database URL, without database/network access:

- The new producer unit tests and unchanged retained-organization unit suite passed **23 tests**.
- The source coverage, activity-binding and publication-date suite passed **33 tests** against the adapter hash above.
- The original positive and **17 additional negative controls** passed. These deny stale document/interpretation/evidence versions; wrong observation, project, location, aliases or source contract; malformed alias spans; foreign, negated, on-behalf-of and different-legal-form actors; cancellation; and a foreign campus reusing the native alias. The last seven exercise native candidate admission plus the producer boundary; the others exercise the public extraction entry point.

The new database integration was inspected, not independently rerun. It checks project-scoped identity creation, stable claim/company IDs on repeated enrichment, and removal of the candidate after cancellation. Its current assertions do **not** query saved BrowseRows or customer groups, so this is claim/identity replay coverage rather than proof of customer-card visibility. The builder reports the integration passing. This addendum accepts the bounded producer implementation for integration; it does not establish broader commercial readiness or authorize operational actions.

Formatter follow-up: the final adapter hash is `44075d0339dc49ad894f96e8aadeb8ae4a6a6190a009393c0b2c5eb511f87256`. Independent diff inspection confirms the same two reviewed guards, with only line wrapping changed since `ece4be5b…`; bounded acceptance carries forward without another test run. Producer and both test hashes above remain unchanged.

Saved-projection follow-up: integration test hash `92ded813020e740e3041c6fa9571c56b08721bb0344f85b60bfac25d4de058e0` adds a published browse rebuild, a canonical Switch group, membership linking the actual project to its current project-scoped company UUID, and the project in that group's detail results. It also checks that generated Needs have no inferred MW. After cancellation and another published rebuild, Switch is absent from canonical groups. These assertions close the earlier saved-projection coverage gap; the builder reports the focused integration passing. This reviewer inspected the added assertions without rerunning the database test. This is an actual retained-source backend projection check, not a browser screenshot or production-state claim.
