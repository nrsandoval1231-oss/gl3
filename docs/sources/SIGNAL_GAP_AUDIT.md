# GL3-015 Signal acquisition gap audit

Snapshot: 2026-09-29, `feat/gl3-015` based on `0199022` (`origin/main` at inspection). Compare with [Signal Source Matrix](SIGNAL_SOURCE_MATRIX.md) and `config/sources/registry.v1.json`. This is a local implementation audit, not a claim that all sources run daily in the cloud. `ACTIVE` below means enabled registry plus earlier local retrieval/persistence/replay proof; upstream freshness for this audit was not reverified. Existing `.agent` receipts are historical proof, not current production telemetry.

## Every configured source

| Registry source | Actual covered event/geography | Readiness and quality limit |
|---|---|
| `austin-building-permits` | Commercial building permits, Austin TX | ACTIVE locally; structured municipal rows; construction centric, not complete planning/electrical lifecycle; status-change query bounded |
| `seattle-building-permits` | Nonresidential building permits, Seattle WA | ACTIVE locally; structured rows; older status edits not monitored by current discovery query |
| `chicago-building-permits` | New construction/renovation permits, Chicago IL | ACTIVE locally; structured rows; two-day status overlap can miss longer outages |
| `georgia-air-draft-title-v` | Current Draft Title V list and selected PDF evidence, Georgia | ACTIVE locally; authoritative air documents; current draft view only, no comprehensive NSR/PSD/issued/renewal history |
| `federal-register-eis` | EIS notices, US federal | ACTIVE locally; structured authoritative notices; narrow EIS query and page-limited document extraction, not all reviews |
| `nc-commerce` | Official facility/project announcements, North Carolina | ACTIVE locally; early project detail; irregular publication and conservative extraction |
| `dcd-news` | Data-center publisher snapshot, global | ACTIVE locally; useful discovery tip, short summary only; item may age out and is not an official permit |
| `utility-dive-news` | Utility publisher snapshot, US focus | ACTIVE locally; secondary reporting, no authoritative project-level large-load docket |
| `manufacturing-dive-news` | Manufacturing publisher snapshot, US focus | ACTIVE locally; secondary reporting and limited feed history |
| `construction-dive-news` | Construction publisher snapshot, US focus | ACTIVE locally; secondary reporting and limited feed history |
| `ogj-exploration-news` | O&G publisher snapshot, global | ACTIVE locally; secondary reporting, no W-2/G-1/P-4/production or fixed facility registry |
| `mjbizdaily-news` | Cannabis publisher snapshot, US focus | ACTIVE locally; topic watch requires manual review; low direct project specificity |
| `taylor-development-newsflash` | Development notices and archive, Taylor TX | **Accepted ACTIVE locally**: current ordinary-worker ingestion, 25 observations/evidence versions, two project/Signal records, three material changes including Mustang withdrawal, unchanged replay and API/browser proof. One-city scope; no deployed cadence |

Historical Texas RRC W-1 files were parsed offline during GL3-015 research. Current-file retrieval and compatibility remain unverified; there is no active RRC registry source. Count live RRC coverage as zero.

## Family assessment

| Family | Coverage, missing stages/jurisdictions/verticals | Source quality; expected value; difficulty |
|---|---|---|
| Land/planning and incentives | Taylor ACTIVE locally, plus NC and publisher announcements. No county recorder, broad zoning, CUP/SUP, parcel, council or incentive acquisition | First-party cases can be early and high value; jurisdiction diversity makes scaling medium/high difficulty |
| Environmental review and stormwater | Federal EIS notices only. No systematic state reviews, 404 or CGP/state construction NOIs | Official records can identify site work; structured availability varies; medium difficulty and duplicate risk |
| Grading, foundation, shell/building | Three city permit feeds; no national/local broad coverage or complete stage normalization | Authoritative and project specific when address/scope present; high value; medium integration difficulty |
| Electrical, temporary service, transformers, substations | Incidental city permits; no targeted electrical/service feed or known completeness | Very high value for lifecycle timing; local terminology and false-positive repairs demand careful selection; medium difficulty |
| Commissioning, load-bank, occupancy, energization | No dedicated source; incidental permits may contain events | High value to update known projects, but public access uneven; medium/high difficulty |
| Air and onsite generation | Georgia Draft Title V only; no broad state NSR/PSD or EPA permit action monitoring | Detailed official evidence, high value; document parsing and renewals add noise; medium/high difficulty |
| Utility/large-load | Utility Dive news only. No project-level ERCOT, utility, PUC/PSC or ISO/RTO docket acquisition | Potentially high value; access and confidentiality vary, project identity may be hidden; research before implementation |
| Upstream O&G | OGJ news only. Historical W-1 parsing had offline proof; no live W-1, completion, P-4, status or production | RRC structured records are authoritative; well/pad consolidation and stage interpretation are material work; medium difficulty after access |
| Fixed O&G infrastructure | Incidental Georgia air and OGJ news; no compressor/processing/pipeline/SWD/injection facility feed | High value if site-specific; sources fragmented across state and federal regulators; medium/high difficulty |
| Other industrial verticals | NC, EIS, city permits and news span some manufacturing/mining/energy; semiconductor, battery, hydrogen, LNG, EV/logistics/remote not systematically covered | Reuse lifecycle model; source and site identity quality vary; medium difficulty |

## Ten highest-value acquisition gaps

Order reflects early appearance, proof of a physical site, future power relevance, geographic reach, reliability, public/structured access, implementation work and noise. It is a practical sequence, not a numeric score or invented probability.

1. **Targeted electrical and temporary-service permits** in accessible structured city datasets. Late but highly power relevant; suppress routine repairs and retain parent permits.
2. **Planning, zoning, CUP/SUP and site-plan cases** from additional first-party jurisdictions with stable case IDs. Earlier than building permits; Taylor alone is insufficient.
3. **Construction stormwater NOIs** from EPA and delegated states with public project location and filing identifiers. Strong site-development milestone; no power-gap inference.
4. **NSR/PSD/new stationary-engine applications** beyond Georgia's current Draft Title V view. Distinguish new equipment from routine renewals.
5. **Foundation/grading and shell stage monitoring** across additional structured municipal feeds, including older permit status changes.
6. **Texas RRC current W-1 plus W-2/G-1 completions, P-4 and production**. The current-file handoff and format compatibility must pass before activation; prioritize completion-to-production transitions over drilling alone.
7. **Public project-level utility/PUC/PSC/ISO records**, starting with a tested Texas route and explicit ERCOT Large Load Integration research. The ERCOT process page alone is not a project feed.
8. **Fixed O&G compressor, processing, pipeline and SWD/injection filings** with facility/site IDs; use state environmental/O&G and FERC dockets where public.
9. **Commissioning, temporary CO/CO and energization notices** linked to known project sites, to show meaningful changes instead of repeat discovery.
10. **First-party economic-development, council and procurement records** beyond North Carolina, including project withdrawals and cancellations.

## This slice and remaining acceptance work

The branch adds a bounded Taylor planning adapter and conservative lifecycle interpretation. The fresh isolated run accepts Taylor as **one ACTIVE local municipal source**: all 13 enabled sources completed; Taylor retained 25 observations and 25 evidence versions, two projects/Signals and three material changes; all source replay digests and counts stayed unchanged. The Mustang card shows its later official withdrawal as current application state while retaining the prior positive notice. Chicago's existing permit query now selects only mapped columns after its prior full-row response exceeded the byte bound. These steps do **not** establish current RRC ingestion, broad Texas/national planning coverage, cloud operation or measured daily cadence.

The [persisted review](../validation/gl3-015-persisted-signal-review.md) covers **all 63 rendered cards** formed from **81 persisted Signal records** in the fresh all-source run: 11 SHOW, 29 REVIEW and 23 HOLD editorial findings. The 23 HOLD cards include transient event permits, routine replacements and repeated hospital work; they remain in the data and review. Same-site multi-building and multi-phase permits remain separate pending stronger linkage. This is an honest quality baseline, not a claim of excellent discovery precision. The current Taylor withdrawal is labeled historical on the card and current application state in the detail.
