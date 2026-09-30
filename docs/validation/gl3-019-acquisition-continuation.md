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
  permit-listed phone fields retained and visible before the existing enrichment
  action. Austin yields **57 organization candidates, 57 permit-listed person
  candidates, and 57 organization permit-listed phone claims** across those projects.
  Employment, person assignment, title and buying authority remain UNKNOWN.
  Phone ownership and business/personal type are UNKNOWN. Phones are not assigned to people.
  Applicant-only organizations retain UNKNOWN project involvement; same-contractor
  spelling variants do not duplicate or demote contractor evidence. A permit-listed
  name without a title cannot contradict an independently sourced current role,
  and cannot lend its citation to another person at the organization. Exact General Contractor and Electrical
  Contractor field values support organization categories. Duplicate/conflicting
  native field labels cannot create relationships; source attribution persists.
- **Houston:** four latest official weekly XLSX reports, August 17–September 14,
  retrieved and persisted through ordinary jobs: **1,543 distinct records**,
  all unchanged on replay. Two exact duplicate source rows are deduplicated;
  conflicting duplicates, changed headers/footer, foreign links, excessive bytes,
  unexpected sheets and stale listing (>30 days) fail visibly. No status or party
  fields exist in these reports. Official page/search/report-definition follow-through
  establishes permit activity and a “permits sold” search, but not an explicit
  issuance/current-status contract for every weekly report row. Therefore **zero Signals** pass existing status gates.
  Records remain in the ingestion inbox, not fabricated project cards. Latest
  published interval is 16 days behind this check; it is not live citywide coverage.

- **RRC:** current official daily file plus the preceding calendar month's official
  end-of-month file are retrieved through ordinary public GoDrive forms. The
  current capture has 966 root/master groups; August EOM has 992. Combining
  amendments yields 1,904 permit identities. Every source byte, including NEL
  continuations in opaque type-08 restrictions, is retained. Original sequence 99
  decrements on amendment; 34 permits overlap months with newer September sequences.
  Prior snapshots cannot replace a newer amendment. Official `P` permit cancellation
  and `F` filing cancellation prevent admission; no active status is inferred from
  a cancelled filing. Current files over four days old, missing previous-month EOM,
  changed framing or exceeded bounds fail visibly. The August EOM is byte-identical
  to the September 2 daily backup; September 3 resets to 36 groups. This observed lag
  is why collection uses the dedicated EOM product, not a guessed first-day backup.
  This is **current plus prior month**, not all historical Texas drilling permits.
  Longer outages and older corrections remain gaps. Drill permits are early-production
  Signals without a proven power gap. Rework permits support a separate field-activity
  question without asserting new drilling. Exact W-1 types are preserved: drilling,
  reentry and recompletion support activity Signals; administrative field transfer
  and reclass remain observations, not invented new drilling. Reentry/recompletion
  do not assert a completed phase. Production date, load, fuel suitability and
  contacts remain UNKNOWN. No production-date heuristic is applied to this feed.

The final ordinary-worker RRC run retained **1,904 observations**, accepted
**1,880 activity Signals** (1,711 drill, 151 recompletion, 18 reentry), and retained
24 administrative field-transfer/reclass records without current Signal admission.
Replay returned **1,904 unchanged**, zero new/changed. The initial pre-review
acceptance run admitted those 24 administrative rows; final re-evaluation closed
them and preserved their historical evidence. No duplicate active well needs or
estimated production dates remain. This is not a clean-history count of 1,904 active
projects: the isolated corpus deliberately retains those superseded decisions.

## Real data-center inspection

- **7000 Burleson Rd Bldg B Unit 100**, `2025-155325 EP`: permit scope explicitly
  describes data-center expansion into an existing shell. Exact fields name
  **Prism Electric Inc / Blake Combs**, contractor permit-listed phone `5129262000`.
- **811 Clayton Ln**, `2026-036762 EP`: modular data-center foundation work;
  **Exceed Electrical Contracting / Adam Stockton**, permit-listed phone `5126672564`.
  Associated `2026-036762 BP` names `Novo Construction **Main**` / **Matt Mullen**,
  with `contractor_trade: General Contractor`. Separate permit identities remain;
  shared company names alone do not merge records.
- These examples are construction evidence. Transformer counts, nameplate,
  permit Active status and foundation dimensions do not prove temporary rental
  demand, commissioning dates, utility delay, load or suitable fuel.
- Authenticated browser acceptance opened Burleson and Clayton through the actual
  project cards/review tabs, clicked enrichment and inspected names, permit-listed
  phones, retained permit facts and UNKNOWN current roles. Existing LaSalle and
  QTS acceptance was rerun. Huron remains a hospital, not a data center.

## Real well/operator inspection

- `0761171`, lease `HAUG-KIESCHNICK AC UNIT 33`, well `1H`: exact operator
  `TRINITY OPERATING (USG), LLC`; original issue 2013-04-24, application received
  2026-08-25, amendment 2026-09-15, sequence 98. These dates stay separate.
- `0780482`, lease `E. BUTLER A`, well `11H`: exact operator `BPX OPERATING COMPANY`;
  application type 14 **Recompletion**, amendment 2026-09-10. Upstream-well asset
  identity remains; completed work and current lifecycle phase are UNKNOWN.
- Operator links are DIRECT permit evidence, with exact `operator:` quotes.
  No named people, personal contacts, job titles, employment or buying authority
  are inferred. Existing enrichment uses retained fields without refetching GoDrive.

## Access and scope still open

- **Dallas:** official permit reports page HTTP 401; DallasNow Accela HTTP 403.
  Historical Dallas Open Data permits explicitly no longer updated. No source
  enabled and no assertion that all other Dallas routes are unavailable.
- **El Paso:** official planning page and Accela Building search HTTP 403.
  No current connector enabled. These are tested endpoint denials, not a claim
  that public permit records do not exist.
- Default project ordering remains recency-based, not a new data-center priority
  rank; site/permit search remains available.
- **Commissioning:** bounded Chicago/Austin searches found decommissioning,
  residential EVSE/solar and unrelated solar commissioning, not data-center
  commissioning. No dedicated commissioning acquisition claim.

## Validation

- Ruff, mypy (46 source files), **418 pytest passes / one existing missing-fixture
  skip**; source bounds, provenance, admission and stale/unsupported role tests.
- Fresh database migrations, repeated upgrade and drift check: pass.
- Frontend typecheck and production build: pass.
- **13 browser passes**: 11 repository checks plus cloud-only real Austin
  and RRC acceptance cases covering two sites/wells each. RRC desktop/mobile
  evidence panels have no horizontal overflow. Chromium sandbox remained enabled;
  all existing repository assertions and timeouts remain unchanged.
- Initial browser login failures were isolated test-origin misconfiguration,
  corrected without changing application security. Initial Houston parse failures
  exposed link variants, duplicate rows and footer metadata; final complete
  workbook and worker replays pass. No failed check was substituted with a fixture.
- The enlarged corpus exposed an existing N+1 list-query bottleneck. Batched reads
  reduced measured requests from **15,507 queries / 10.37 seconds** to **7 queries /
  1.47 seconds** for 1,981 active opportunities. Admission checks, facts and evidence
  match the original response; equal-timestamp companion evidence now has a stable
  hash tiebreak. Encoded raw RRC bytes remain stored but are omitted from the readable
  UI excerpt, with long source references wrapping on mobile.
- Global replay: 7,603 observations, 9,583 evidence versions, 2,005 historical
  projects, 2,174 historical needs; zero duplicate source/project identities,
  evidence versions or claim fingerprints, and zero unsupported load/supply facts.
  Historical inactive needs remain inspectable; 1,981 opportunities are active.
- Final evidence/identity/replay manifest and independent review are recorded
  alongside the final candidate. Hosted CI previously failed to start because
  of account billing limits; executor validation does not imply hosted success.

The exact reviewed code candidate is `bc17fb374f41920aac47d603ea2634227b7029fa`.
Changed-file hashes, authoritative RRC framing proof,
source health, real project/organization/contact examples and replay checks are in
[the final evidence manifest](gl3-019-acquisition-evidence.json). Prior raw transport
width concerns were resolved against the official copybook and all retained bytes;
they were ordinary implementation work, not a source-access denial.

Raw official captures, database proofs, browser screenshots and run logs remain
in ignored `.artifacts/gl3-019-continuation/` and `web/test-results/`.
