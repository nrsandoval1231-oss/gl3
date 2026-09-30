# GL3-018 local acceptance

Date: 2026-09-30. Base: GitHub main
`1f18a0182922fe8ee3fdc2225cf9c3f7c95d1fea` (merged GL3-017, PR #7).
Branch: `feat/gl3-018`. No merge or deployment authorized.

## Delivered behavior

Standalone opportunity admission now requires accepted, exactly bound authoritative
permit evidence, a project-specific official utility filing, or an explicit official
temporary-power solicitation. News is retained as evidence and can supplement one
supported physical project/activity. General news and ambiguous project/site/phase
matches do not create opportunities. Planning/entitlement remains research context;
the owner has not approved it as a standalone origin. Admission applies at persistence
and API read, including old unsupported opportunities, rather than reducing a score.

Migration 0009 adds admission provenance and closes unsupported active needs while
retaining their previous active/tier state and all projects, links, observations and
evidence. Current source versions must support the exact project and power activity.
An older link is not permission to apply another project's current assessment.

The registry still has 13 sources. Existing Georgia acquisition now extracts bounded,
page-cited generator/engine technical context from the full narrative/draft PDF text,
preserving raw PDF hashes and extraction versions. Quantities use decimal kW/1,000
conversion, with regulatory context identified and equipment/campus/current/historical
scope left unassigned when the text does not establish it. Existing Chicago acquisition
now includes Express Permit Program Electrical Work and retains parcel and contractor
fields. See [scope and exact caps](../sources/gl3-018-admission-and-acquisition.md).

## Ordinary-worker live proof

The application database began empty for this slice. `sync_registry`, durable
`enqueue`, and ordinary `run_one` → `process_job` used production adapters and the
environment's supported HTTP transport. No project seeds, source fixtures, patched
clients, tunnels, custom DNS, or disabled security controls were used. Buying-chain
SSRF/DNS/IP/TLS behavior is unchanged.

Initial acquisition and unchanged replay:

| Source | Retained observations | Admission | Documents |
| --- | ---: | --- | --- |
| Georgia EPD | 19 | 9 Signals, 10 rejected | 38 PDFs |
| Chicago | 1,528 | 16 Signals, 1,512 rejected | Official structured rows |
| DCD | 20 | No independent opportunities | RSS evidence |

Initial replay left 1,567 observations, 1,605 evidence versions, 25 projects, 25 needs
and 25 change events unchanged. Re-extraction under the corrected generator extractor
retained earlier evidence and increased the final evidence total to 1,719 and events to 43,
with the same 25 projects/needs. Georgia retained 417 technical excerpts; another 147
were omitted by its disclosed per-document caps. A later Chicago refresh returned an
HTTP error, visibly failed source health, and preserved previously accepted data.
The final ordinary-worker retry and replay succeeded for all three sources, leaving
those counts unchanged. All 25 API opportunities display the Official permit origin.
The machine-readable report preserves the failed intermediate run as well as final
successful outcomes.

Reviewed real records include:

- Chicago `N2982771`, 2333 W Monroe: temporary 100 A service, with named electrical
  contractor. Amperage does not establish MW.
- Chicago `N2977370`, 5848 S University: temporary 60 kW diesel generator for a special
  event. It is a permit Signal, not a proven open rental solicitation or sales Lead.
- Chicago `3459792`, 333 E Huron: two 2,000 A temporary services; and `3451848`,
  400 S LaSalle: phase-specific data-center conversion. Earlier permits cited in its
  scope are not fabricated as retrieved evidence.
- QTS Fayetteville application 30027, Apex Site Solutions/Hampton 30108, and
  TADG–ATL02/Ellenwood 30104: accepted current Georgia filings with source-linked
  narratives/drafts. Standby capacity and partial service claims do not establish
  temporary rental MW or an unmet supply requirement.
- Bonnell Aluminum: retained/rejected routine Title V renewal. DCD's Trane 2.5 MW
  product announcement and Google/Crusoe Amarillo customer article remain news
  evidence and produce no independent Signals.

[Exact source URLs, hashes, reviewed excerpts, job outcomes, source health and counts](gl3-018-live-evidence.json)
are public-source evidence exported from this local database. All 25 exposed needs
retain unknown required MW and unknown suitable supply. No live Prospect/Lead is claimed.
The current DCD sample lacks an exact supported-project news match; regression fixtures
prove supplemental matching, not live discovery of such a match.

## Final local checks

| Check | Result |
| --- | --- |
| Backend Ruff, including migrations (`ruff check .`) | Passed |
| mypy (`mypy src`) | Passed, 43 source files |
| Full pytest (`pytest tests -q -rs`) | 381 passed, 1 existing skip |
| PostgreSQL 17.11 clean upgrade, repeated upgrade, `alembic check` | Passed, no drift |
| Populated 0009 migration regression | Passed: permit stays active; news closes; history/links retained |
| Generated OpenAPI and TypeScript contracts | Regenerated |
| Frontend typecheck and production build | Passed |
| npm audit | Zero vulnerabilities |
| Playwright | 9 passed, including three authenticated real-database tests |
| Diff whitespace check | Passed |

The existing skip is `test_nc_commerce.py`'s absent optional local access probe.
Starlette emits its existing httpx TestClient deprecation warning. No test or CI
protection was disabled. Four older migration files received import/format-only
cleanup to pass the broader Ruff run; non-import ASTs were verified unchanged.
The new migration is tested both on an empty database and populated historical rows.

Regression coverage includes news-only rejection, permit admission with unknown MW,
qualified utility/procurement fixture admission, news before/after its permit,
exact-site matching versus city-only/multiple candidates, singular/plural/ranged
phase ambiguity, moved A→B news remaining historical on A, replay/provenance refresh,
duplicate and withdrawal history, fencing, failed parsing and bounded partial work.

Browser acceptance used the installed Chromium with its sandbox enabled. The normal
restricted process sandbox could not initialize Chromium's SUID sandbox; approved
execution outside that restriction preserved browser security. Desktop permit detail,
mobile source health (390 px, overflow checked), and the live Georgia generator
evidence section were captured and visually inspected. Raw screenshots/logs remain
outside Git under `.artifacts/GL3-018/`. Mocked browser tests are explicitly separate
from the three real-database tests.

The candidate manifest and frozen independent review accompany the draft PR.
Tests distinguish real worker/UI acceptance from explicit synthetic regression fixtures.
The previous GL3-017 live-validation claim is owner-reported, not fresh proof from this
agent; its historical saved-cloud failure remains documented in CURRENT_STATE.

## Remaining limits

- All 19 live Georgia application-link fields are empty. This slice retrieves narratives
  and drafts, not full air applications. Nine public-notice references are not extracted.
- No utility docket, direct rental/load-bank procurement, commissioning or RRC connector
  was added. Utility/procurement admission is policy/regression coverage only. The chosen
  accessible first-party addition within an existing route is Chicago Electrical Work.
- The reference Library ZIP was resolved with the current materialization skill, but
  signed-blob transfer failed and no readable bytes were obtained in this consumer.
  The supplied research synthesis informed scope; the ZIP is not claimed as inspected.
- Direct pinned-IP HTTPS is prohibited in this environment. Existing production source
  adapters succeeded over the approved proxy; no buying-chain security bypass was made.
- National coverage, scheduled unattended operation, commercial conversion, and launch
  acceptance remain open. No source count or forced Signal quota substitutes for them.
