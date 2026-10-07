# Project Jupiter — scoped reconciliation, October 7, 2026

## Inspection and delivery boundary

Inspected GitHub main `94c3acb7b36c6d5d04a77a0ec445e793e05120a4`.
Open PRs 28–31 cover scheduler repairs, Texas interconnection, ERCOT RFI and SPS
tariffs; none covers Jupiter. Repository search found no retained Jupiter project
record (only an RSS rejection test). No live application/database endpoint or
Jupiter project UUID was available. This is a reviewed reconciliation and a
classifier repair, **not a live record update or verified no-change result**.

The existing Evidence model retains publication/event/retrieval dates and source
links. Research claims bind project, power activity and evidence version, but
their six fields do not represent court procedure or a separate power facility.
The lifecycle classifier instead scans whole-document keywords. Six reproductions
showed mixed reports incorrectly lending construction, formation or energization
support to the campus, including previously accepted retained events.

## Reconciled signals (source facts and attribution)

| Track / subject | Dated evidence | Retained state | Authority / limits |
|---|---|---|---|
| Campus construction | Oracle statement published September 14 | Oracle reports campus work under county permits, on a site adjacent to the separately operated microgrid | First-party company statement, not independently inspected county permits. No campus stop is established by this statement. |
| Microgrid / air permit | Same September 14 statement; NMED October 2 notice | Separate microgrid permit process; application NSR 10883, docket AQB 26-57(P) | Oracle identifies the facility separation. NMED identifies applicant Yucca Growth Infrastructure LLC and the pending permit matter. Appointment is not permit issuance or permission to build the emitting source. |
| Court procedure | Source NM September 17 report of that day's rulings | Two challenges denied and stays lifted; regulatory proceedings allowed to resume | Secondary reporting; primary Supreme Court orders not inspected. This is procedural progress, not permit approval. |
| Hearing administration | NMED October 2 notice, page 1; Sun-News report published October 6 | James O. Browning replaces Max Shepherd; John Rhoderick retains final/dispositive decisions | Primary notice inspected. Notice sets no hearing date. Sun-News reports no hearing scheduled as of the morning of October 5; do not silently extend that observation to October 7. |
| Commercial power-delay risk | Reuters report September 24, retrieved through its MarketScreener syndication | Force-majeure notice reportedly concerns potential power delays; actual notice date and text not independently verified | Reuters cites an unnamed source. Oracle's on-schedule position and Blue Owl's unchanged financial-commitment position remain separately attributed. Neither cancellation nor an actual quantified delay is established. |

Do not collapse these into one project status. Campus construction and pending
power-facility authorization can coexist. The September 17 procedural development
supersedes the September 14 statement's description of an active stay; it does not
supersede Oracle's separate-facilities assertion. The October 2 appointment
supersedes September 17 reporting that a replacement officer had not been appointed.

### Date discrepancy retained

The October 6 Sun-News/AOL report says September 18 for the stay lifting, while
Source NM's contemporaneous September 17 report says September 17. Use September 17
as **reported by Source NM**, retain the conflicting September 18 attribution, and
resolve against the court orders before calling the event date primary-verified.
The October 6 article also says August 2025 for Shepherd's recusal; the inspected
NMED notice explicitly refers to an order filed August 22, 2026. Preserve the
primary notice date rather than copying that apparent year error.

## Source hierarchy and provenance

Authority is claim-specific: NMED is authoritative for its appointment; Oracle is
the direct source for its corporate position, not an adjudicator of legality.
Reuters and local reporting remain secondary for documents not inspected. A newer
publication does not automatically override a primary event date or unrelated track.
All sources below were retrieved October 7, 2026.

1. [Oracle, September 14](https://www.oracle.com/news/announcement/project-jupiter-statement-on-construction-permitting-2026-09-14/).
2. [Source NM, September 17](https://sourcenm.com/2026/09/17/new-mexico-supreme-court-rejects-2-project-jupiter-challenges-allows-permitting-process-to-resume/).
3. [NMED notice, October 2](https://www.env.nm.gov/opf/wp-content/uploads/sites/13/2026/10/2026-10-02-AQB-26-57-Notice-of-Substitution-of-Hearing-Officer.pdf).
   Downloaded PDF SHA-256: `76fd32118d24d483cd9d9d7075317c1ff72d9ef0583ac9d8cc6076f349126511`.
   Scanned document: page 1 visually inspected, including received stamp and signature.
4. [Sun-News syndicated by AOL, October 6](https://www.aol.com/articles/retired-judge-lead-project-jupiter-090622000.html).
5. [Reuters canonical URL, September 24](https://www.reuters.com/business/oracle-cites-force-majeure-shield-itself-controversial-data-center-bloomberg-2026-09-24/)
   was inaccessible directly. Read [Reuters syndication at MarketScreener](https://www.marketscreener.com/news/oracle-cites-force-majeure-to-shield-itself-on-data-center-bloomberg-news-reports-ce785adede8cfe2d).

## Small production repair

`requires_scoped_lifecycle_evidence` makes the keyword classifier abstain on
data-center narratives mentioning a microgrid, force majeure, or an air-permit
court/hearing/proceeding. It applies to both new classification and retained-event
support during projection. Evidence/history remains retained. Single-facility
building-permit evidence remains classifiable. No schema migration or project-name
special case is introduced; no cancellation, pause, approval, MW, buyer, timing,
gap duration or commercial tier is inferred.

Tradeoff: an otherwise valid campus milestone inside a mixed report also abstains.
A separately scoped source is needed; this does not extract multiple tracks from
arbitrary prose. This reconciliation is retained here for review, not automatically
imported as source evidence. A general facility-scoped claim ingestion/UI system is
not delivered by this patch. Existing exact-project research parsing already
refuses the tested risk/procedure/schedule statements as cancellation or energization.

## Remaining live acceptance

Locate the live Jupiter record and original evidence, inspect any accepted mixed
lifecycle observations, then refresh its projection in an isolated validation copy.
Retain independently supported campus construction. Bind microgrid/permit/court
and contractual-risk facts to their proper subjects with the dates and attributions
above. Check the current NMED docket for any hearing date after October 5. Obtain
the court orders and county permit records before upgrading those claims' authority.
Potential power-delay risk warrants research; it does not establish rental demand,
an available procurement path, a 2G-sized load, fuel readiness, start or duration.

## Validation

- Red: six new cases failed on main behavior; five controls already passed.
- Green: all 11 new cases plus existing lifecycle, project-research and news
  interpretation tests: **94 passed**. Changed-file Ruff passes.
- Broader unit run: **864 passed, 1 failed, 1 skipped, 1 setup error**.
  Failure: `test_retained_reconstruction_rejects_deeply_nested_json_as_source_parse_error`
  in unchanged RRC tests expects a different error message on this runtime.
  Setup error: `test_georgia_job_retains_null_publication_and_replays_with_pdf_evidence`
  requires PostgreSQL; localhost:5432 refused the connection.
- Full-suite attempt stopped after the first three PostgreSQL setup errors in
  `test_autonomous_questions_integration.py`: two-distinct-target jobs, daily cap,
  and fresh-cache force case. No full-suite pass claimed.
- Runtime: Python 3.12.14, while the repository pins Python 3.11. Existing
  Starlette/httpx deprecation warning. Python 3.11/PostgreSQL validation remains open.
- Initial test harness attempts lacked scripts/registry files or test settings;
  these were corrected before the reported runs. Main backend/scripts/config inputs
  were checked against GitHub blob hashes (203 files); changed source baselines
  matched main after removing snapshot-added trailing blank lines.

No live database mutation, corpus replay, UI acceptance, merge or deployment.
