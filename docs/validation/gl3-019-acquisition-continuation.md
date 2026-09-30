# GL3-019 acquisition continuation — 2026-09-30

Continues draft PR9; no merge or deployment. Supersedes the original GL3-019
acquisition totals, while retaining its Chicago/Georgia evidence and acceptance.
Documentation scope was updated before implementation. Work stayed in the saved
cloud environment. Normal public requests were used; no source restriction bypass.

## Implemented and live-validated

- **Austin:** commercial Building + Electrical permits, 30-day issuance and
  seven-day status overlap. The same counted query unions a fixed initial
  2026-01-01–2026-09-30 literal `data center` / `data centre` backfill. It rechecks
  these historical rows on subsequent refreshes without advancing that cutoff.
  This is not all data-center work. Existing page/byte/count/order limits remain.
  Live: **2,609 rows**, **78 accepted permit observations across 76 projects**;
  replay: 2,609 unchanged, zero new/changed. No Prospect/Lead promotion.
- **Permit enrichment:** exact contractor/applicant organization, name, trade and
  business-phone fields retained and visible before the existing enrichment
  action. Austin yields **57 organization candidates, 57 permit-listed person
  candidates, and 57 organization business-phone claims** across those projects.
  Employment, person assignment, title and buying authority remain UNKNOWN.
  Phones are not assigned to people. Exact General Contractor and Electrical
  Contractor field values support organization categories. Duplicate/conflicting
  native field labels cannot create relationships; source attribution persists.
- **Houston:** four latest official weekly XLSX reports, August 17–September 14,
  retrieved and persisted through ordinary jobs: **1,543 distinct records**,
  all unchanged on replay. Two exact duplicate source rows are deduplicated;
  conflicting duplicates, changed headers/footer, foreign links, excessive bytes,
  unexpected sheets and stale listing (>30 days) fail visibly. No status or party
  fields exist in these reports, so **zero Signals** pass existing status gates.
  Records remain in the ingestion inbox, not fabricated project cards. Latest
  published interval is 16 days behind this check; it is not live citywide coverage.

## Real data-center inspection

- **7000 Burleson Rd Bldg B Unit 100**, `2025-155325 EP`: permit scope explicitly
  describes data-center expansion into an existing shell. Exact fields name
  **Prism Electric Inc / Blake Combs**, contractor business phone `5129262000`.
- **811 Clayton Ln**, `2026-036762 EP`: modular data-center foundation work;
  **Exceed Electrical Contracting / Adam Stockton**, business phone `5126672564`.
  Associated `2026-036762 BP` names **Novo Construction **Main** / Matt Mullen**,
  with `contractor_trade: General Contractor`. Separate permit identities remain;
  shared company names alone do not merge records.
- These examples are construction evidence. Transformer counts, nameplate,
  permit Active status and foundation dimensions do not prove temporary rental
  demand, commissioning dates, utility delay, load or suitable fuel.
- Authenticated browser acceptance opened Burleson and Clayton through the actual
  project cards/review tabs, clicked enrichment and inspected names, business
  phones, retained permit facts and UNKNOWN current roles. Existing LaSalle and
  QTS acceptance was rerun. Huron remains a hospital, not a data center.

## Access and scope still open

- **Dallas:** official permit reports page HTTP 401; DallasNow Accela HTTP 403.
  Historical Dallas Open Data permits explicitly no longer updated. No source
  enabled and no assertion that all other Dallas routes are unavailable.
- **El Paso:** official planning page and Accela Building search HTTP 403.
  No current connector enabled. These are tested endpoint denials, not a claim
  that public permit records do not exist.
- **RRC:** official current `daf420.dat` download verified twice, 2,623,180 bytes,
  SHA-256 `4bf8b0f65a6e3f077802d9e95ea33bd184c6b0d3ca452efa49129915ea895fc3`.
  Root-only inspection: 966 distinct status/sequence records, 949 permit numbers;
  dates span 2013–2026. The OGA049M guide describes 510-byte tape records; live
  download uses variable-length segments, with 57 CRLF fragments lacking a record
  prefix. Full framing, amendment sequencing and monthly rollover recovery are
  unvalidated. **No RRC ingestion enabled**; retrieval is feasible, not denied.
  Drilling permits remain valid early-production Signals when ingested reliably;
  this work does not establish production dates, power load or supply gaps.
- **Commissioning:** bounded Chicago/Austin searches found decommissioning,
  residential EVSE/solar and unrelated solar commissioning, not data-center
  commissioning. No dedicated commissioning acquisition claim.

## Validation

- Ruff, mypy (45 source files), **390 pytest passes / one existing missing-fixture
  skip**; source bounds, provenance, admission and stale/unsupported role tests.
- Fresh database migrations, repeated upgrade and drift check: pass.
- Frontend typecheck and production build: pass.
- **12 browser passes**: 11 repository checks plus one cloud-only real Austin
  acceptance case covering both sites. Chromium sandbox remained enabled.
- Initial browser login failures were isolated test-origin misconfiguration,
  corrected without changing application security. Initial Houston parse failures
  exposed link variants, duplicate rows and footer metadata; final complete
  workbook and worker replays pass. No failed check was substituted with a fixture.
- Final evidence/identity/replay manifest and independent review are recorded
  alongside the final candidate. Hosted CI previously failed to start because
  of account billing limits; executor validation does not imply hosted success.

Raw official captures, database proofs, browser screenshots and run logs remain
in ignored `.artifacts/gl3-019-continuation/` and `web/test-results/`.
