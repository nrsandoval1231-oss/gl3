# GL3-017: project-specific buying-chain enrichment

Status: merged to main as PR #7, commit `1f18a01`. The sections below are the
pre-merge validation record. Sentences that say to keep PR #7 draft describe
that saved-cloud live-retrieval result. Later owner-reported live acceptance is
not fresh proof in this file. GL3-018 later merged authoritative admission on
the same main line. Deployment is not authorized.

## Scope and boundaries

GL3-017 adds an explicit, bounded enrichment action for an existing physical
Project ID. It reuses GL3-016 project identity and accepted source evidence. It
never merges cards by company name, creates a generic contacts database, sends
outreach, changes a Signal's tier, or changes power/load/supply claims. It does
not add sources to the ingestion registry. GL3-018 was a later slice.

This is conservative extraction, not a general autonomous research agent. The
service starts from accepted retained evidence. For Chicago permits it retrieves
one exact official permit row to inspect contractor fields absent from the
Signal summary. Other projects use their retained source URLs. The user may add
up to four public project or organization links; only a bounded number of
relevant same-host links are followed. There is no general web search. Results
are capped at eight candidates, with unresolved gaps preserved instead of
inventing entries to satisfy a three-to-eight target.

## Relationship contract

Each candidate retains three separate claims:

1. Project → organization: explicit involvement evidence, or UNKNOWN
2. Organization → person: supported current role, or UNKNOWN
3. Person → project: DIRECT explicit assignment, ROLE_SUPPORTED relevant current
   role at an involved organization, or UNKNOWN

ROLE_SUPPORTED is not personal project assignment and never establishes
purchasing authority. DIRECT involvement likewise does not prove who controls a
temporary-power package. Missing, conflicting, superseded or stale evidence must
remain inspectable. Current roles on undated sources cannot borrow an invented
publication date. Historical publication dates are not refreshed by retrieval.

Electrical contractors, GCs, EPCs, commissioning teams and relevant construction,
energy or procurement leadership take priority. Operator/field roles are retained
for O&G; a construction buying-chain template cannot establish an asset's
commercial structure. Rental intermediaries are excluded as pursuit targets.
Only explicitly attributed public business contact details can be included.

Evidence strength is qualitative, not a probability: High means an explicit
supported involvement/assignment claim; Medium means a supported current
organization role with personal project assignment unproven; Low marks ambiguous,
conflicting, aged or superseded support. Strength never substitutes for a missing
relationship or a commercial qualification gate.

The shared 35-second retrieval deadline is cooperative, not a guaranteed hard
wall-clock cap. Requests and streamed chunks check the remaining budget; active
synchronous transport phases and operating-system DNS resolution cannot be
preempted by that check. Document, candidate, URL and byte caps apply separately.


## API and storage

- Authenticated `GET /api/projects/{project_id}/buying-chain` reads retained findings
- Authenticated, same-origin `POST /api/projects/{project_id}/buying-chain/enrich`
  runs one bounded pass; optional body: `{"source_urls": ["https://…"]}`
- `GET` with `history=true` exposes retained claim versions
- `0008_buying_chain` adds project-bound evidence, immutable relationship claims
  and run results; it does not modify discovery observations or tier decisions
- Retained-source excerpts link back to existing Evidence IDs where applicable;
  new source excerpts retain URL, content hash, extraction location and dates
- Source content and semantic claim identity control replay; retrieval times must
  not create duplicate people or claims

The existing project-detail UI shows these separate relationships, unknown
contacts, evidence disclosures, stale-role warnings and research history. It
retains findings on errors and ignores results that arrive after navigating to a
different project. Repeated clicks are suppressed while the request is pending.

No new model calls are introduced. Jev remains the existing bounded GL3-016
ambiguity adjudicator, never a source of invented people or commercial facts.

## Earlier execution limitations (superseded in part below)

Two execution limits must not be mistaken for passing acceptance:

- Direct application retrieval cannot resolve public DNS in the cloud shell.
  Independent live source retrieval through the connected research service
  succeeds. Captured real-source parser/persistence checks therefore do not
  prove the application's direct live discovery path in this environment.
  Public-only URL/IP restrictions and TLS validation are retained.
- Playwright's browser download returned malformed bytes; installed Chromium
  cannot create its required Unix socket. The supported cloud browser rejected
  a local-file preview under its URL policy. Browser interaction/visual tests
  remain unverified; type checking and build are separate checks.

The owner subsequently authorized conditional merge after our own complete
validation. The saved-cloud rerun below closes browser execution but leaves live
retrieval blocked. PR #7 later merged. Deployment remains unauthorized. The
instruction to keep the PR draft was the status when this live-retrieval gate
was still blocked.

## Manual real-source review, 2026-09-30

The sample uses three already-retained GL3-016 Chicago projects: one data-center
conversion, one hospital temporary-electrical-service project and one
manufacturing renovation. These are not three data centers. Exact municipal
record IDs anchor identity; the current contractor row does not establish an
open power package or personal purchasing authority.

| Existing project | Organization involvement | Current role source | Person → project |
| --- | --- | --- | --- |
| Chicago 3459792, 333 E Huron: two temporary electrical services | Official permit names Gurtz Electric Company as electrical contractor and Power Construction as GC | Gurtz biography: David Steffenhagen serves as Director of Construction Operations | ROLE_SUPPORTED only; direct assignment UNKNOWN |
| Chicago 3451848, 400 S LaSalle: data-center conversion, Phase 3 | Official permit names Kelso-Burnett, ABCO and Bonus Electric as electrical contractors; ARCO/Murray as GC | Kelso-Burnett current roster: Jeff Weir, President | ROLE_SUPPORTED only; direct assignment UNKNOWN |
| Chicago 3442494, DMG Mori manufacturing renovation | Official permit names Kelso-Burnett as electrical contractor | Same current Kelso-Burnett role source | ROLE_SUPPORTED only; direct assignment UNKNOWN |

Primary citations:

- [Permit 3459792](https://data.cityofchicago.org/resource/ydr8-5enu.json?$where=id%3D%273459792%27&$limit=5)
- [Gurtz current biography](https://gurtzelectric.com/david-steffenhagen/)
- [Permit 3451848](https://data.cityofchicago.org/resource/ydr8-5enu.json?$where=id%3D%273451848%27&$limit=5)
- [Kelso-Burnett current roster](https://kelso-burnett.com/about)
- [Permit 3442494](https://data.cityofchicago.org/resource/ydr8-5enu.json?$where=id%3D%273442494%27&$limit=5)
- [ARCO/Murray corroborating project announcement](https://www.arcomurray.com/arco-murray-and-legacy-investing-partner-on-chicago-data-center-conversion/)

All five primary sources were retrieved live through the connected research
service with HTTP 200. The [capture manifest](gl3-017-source-manifest.json)
records retrieval times, hashes and transformations. Organization biography/roster
publication dates are UNKNOWN; municipal issue dates are event dates, not source
publication dates. No email or phone was guessed. Named personal project
assignment, buying authority, procurement availability, power MW, timing and
supply gaps remain UNKNOWN.

A supplemental QTS Fayetteville campus review was deliberately excluded from
these three chains. Its official campus page mentions Clayco and HITT and also
routes current site-work inquiries to Brasfield & Gorrie; this does not resolve
which contractor controls a particular permit entity, phase or power package.
Clayco's current Ryan McGuire biography does not establish individual assignment
to that project. Campus-level names must not be silently upgraded to a specific
phase's buying chain.

## Real-source manual acceptance sample

All three identities already occur in the committed GL3-016 corpus. The cloud
workspace has no copy of the interrupted local database, so parser/persistence
acceptance reconstructs only their original corpus identities and accepted
source evidence in an isolated test schema. It does not seed contractor or
person claims. Source captures and hashes are described in
[the capture manifest](gl3-017-source-manifest.json).

1. **Chicago 3459792, 333 E Huron Street:** the
   [official permit row](https://data.cityofchicago.org/resource/ydr8-5enu.json?$where=id%3D%273459792%27&$limit=5)
   describes temporary electrical services and lists Gurtz Electric Company as
   electrical contractor. Gurtz's
   [current biography](https://gurtzelectric.com/david-steffenhagen/) identifies
   David Steffenhagen as Director of Construction Operations. Organization
   involvement is DIRECT; the person's relationship is ROLE_SUPPORTED.
2. **Chicago 3451848, 400 S LaSalle Street:** the
   [official permit row](https://data.cityofchicago.org/resource/ydr8-5enu.json?$where=id%3D%273451848%27&$limit=5)
   describes the data-center conversion and lists Kelso-Burnett, ABCO and Bonus
   electrical contractors plus ARCO/Murray general contractor. Kelso-Burnett's
   [current leadership roster](https://kelso-burnett.com/about) identifies Jeff
   Weir as President. His project relationship is ROLE_SUPPORTED, not DIRECT.
3. **Chicago 3442494, DMG Mori manufacturing renovation:** the
   [official permit row](https://data.cityofchicago.org/resource/ydr8-5enu.json?$where=id%3D%273442494%27&$limit=5)
   lists Kelso-Burnett as electrical contractor. The same verified current Jeff
   Weir role supports a separate project-specific ROLE_SUPPORTED chain. This is
   not a third unique person and does not imply a personal assignment.

For all three, personal project assignment, temporary-power purchasing authority,
package availability and a remaining power gap are UNKNOWN. No guessed business
email or phone is supplied. Permit issue dates are event dates; source publication
dates remain UNKNOWN. A relevant contractor or executive is a discovery path,
not proof of a qualified Prospect or Lead.

A supplemental QTS Fayetteville campus review found Clayco involvement and a
current Ryan McGuire construction/Compute leadership role, but the QTS page names
multiple contractors and directs current site-work inquiries elsewhere. Exact
phase/package assignment remains unresolved. It is not counted as one of the
three primary acceptance chains or used to fill an evidence gap.

## Previous captured-candidate validation (2026-09-30)

- Ruff `src tests`: passed; portable capture validator Ruff check also passed
- Mypy `src`: passed across 41 source files
- Full `pytest tests -q -ra`: **356 passed, 1 skipped**; the existing North Carolina
  Commerce local-access probe fixture is absent (`test_nc_commerce.py:137`)
- PostgreSQL 17.11: empty database → `0008_buying_chain`, repeat upgrade and
  `alembic check` passed; no migration drift
- Regenerated OpenAPI/TypeScript contract, web typecheck and production build passed
- npm audit: zero vulnerabilities
- Non-browser project-grouping regression: 1 passed; all eight Playwright specs
  list successfully. Browser-dependent specs remain **not executed**, not passed
- Final captured-real-source validator: **PASS_CAPTURED_SOURCE_ONLY**, with
  3/8/6 candidates for the Huron/LaSalle/DMG Mori projects respectively
- Committed round-trip replay: 17 relationship claims, 9 buying-chain evidence
  versions and 3 run rows unchanged. All original Signal tiers and power fields
  remained unchanged; no named person was promoted to DIRECT project assignment
- Every final citation was checked as an exact substring of its retained version;
  canonical metadata participates in version identity. The result file records
  code hashes before/after and the prior failed Gurtz parser attempts honestly
- `git diff --check`: passed. Source registry, qualification gates and GL3-016
  project-identity implementation are unchanged

[Detailed results](gl3-017-real-acceptance.json) include all candidates, roles,
evidence, unknowns, source URLs, capture hashes and replay checks. The primary
named chains are David Steffenhagen and Jeff Weir; the Kelso roster also supports
Corey Gates, Mark Weir and Tony Arnone as SVPs, all ROLE_SUPPORTED only. Public
contact details remain unknown in this real sample. Strict explicit-name contact
extraction is covered synthetically; footer contacts are not assigned to people.

The independent review regressions cover wrong-project clauses, geography and
sibling-name conflicts, permit street-number boundaries, negation, historical
rosters and false publication dates, exact-version citations, A→B→A reobservation,
separate-source role conflicts, stale roles, unchanged replay, preserved accepted
assignments during outages/bounded omissions, and processing-failure preservation.
At that stage, those checks did not remove the direct-network and browser release blockers. The saved-cloud results below supersede the browser limitation.


## Saved-cloud rerun, 2026-09-30

The remote candidate was verified as `814e9e5c0434d2a5eaf42fee9de0528c2cc8a5e7`
before work. The only application change is a reviewed one-line UI correction:
an empty buying-chain result no longer says “Previously retained findings remain
below.” The optional candidate array remains safely guarded. The existing mobile
browser test exposed this defect; no test assertion was weakened.

**Browser execution is now verified:** all eight existing frontend tests pass
(seven browser-dependent tests and one pure grouping test), using Chromium
151.0.7922.173 with `chromiumSandbox: true`. The execution sandbox prevented the
initial launch; an approved execution outside that sandbox worked without
`--no-sandbox` or changing browser protections. Desktop/mobile screenshots were
inspected. Checks cover relationship/evidence disclosure, 503 preservation,
pending/repeated actions, late responses after project switching, empty/UNKNOWN
mobile state, source-link validation, history/navigation, grouping, and filters.
Two authenticated tests use the real local API and PostgreSQL with the three
reconstructed committed corpus identities. The other interaction cases use
explicit synthetic API fixtures. None proves newly retrieved live contacts.

**Live enrichment remains blocked.** The unchanged production enrichment service
was run and replayed for all three documented identities, with their existing
source URLs and Gurtz/Kelso role links, without injecting a fetcher or claims.
Every external retrieval failed with `socket.gaierror: [Errno -3] Temporary
failure in name resolution`, even outside the execution sandbox. A separate
proxy connectivity probe returned HTTP 403 for the Chicago CONNECT request.
Each project durably reports `unresolved`, zero candidates, and the failed source
URLs. Replays retained three run rows, three retained-corpus evidence rows and
zero relationship claims across the three projects. Signal/power fields were
unchanged. No fresh Gurtz/David Steffenhagen or Kelso/Jeff Weir chain was verified.
The earlier captured results remain historical partial proof; the capture bodies
are absent here and were not substituted for genuine retrieval.

Final checks on the repaired application: **356 backend tests passed, one existing
local-probe skip**; Ruff and mypy (41 files) passed; PostgreSQL 18.4 clean/repeat
migration and schema-drift checks passed; web typecheck/build passed; npm audit
reported zero vulnerabilities; regenerated API contracts have no diff. An
independent reviewer checked the corrected UI blob
`a0520538b62a9974007edff0c168dc69409f33f0` and independently passed typecheck and
diff checks. Earlier setup/test failures and their corrections are recorded in
the [saved-cloud validation report](gl3-017-cloud-validation.json).

At the time of this record, the owner’s own-validation merge condition was **not met**
by this saved-cloud run. PR #7 subsequently merged; this file is not fresh proof
that live retrieval succeeded. No hosted CI,
branch protection, application retrieval security, or browser protection was
changed. No deployment occurred. Personal assignment, purchasing authority,
package availability, MW, timing and supply gaps remain UNKNOWN.
