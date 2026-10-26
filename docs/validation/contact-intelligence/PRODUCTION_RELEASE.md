# Production release: company contact intelligence v12

**Release status: bounded capability released. Commercial P0 remains OPEN.** PR #122 merged as `3ce9e8a68a6b988d1d8bfd8597e150f19ae36498`. The reviewed application source is `559b325ea3c3c982a4cdee7af52fb703e2622f13` with tree `4aafcebc8c1a97923b6e9444c98037b4d3600632`. This report describes that frozen release evidence. Later in-progress source changes are outside its evidence boundary.

The product discovers source-published company contact methods, preserves evidence and dates, carries company identity through related project/need contexts, and displays routes in the existing experience. Published routes do not prove reachability, deliverability, procurement authority, or that a named professional controls a purchase. No outreach was performed.

## Current production result

The first bounded production census covered 185 existing Signal companies, all in Texas: 4 data-center and 181 upstream-well companies. Fourteen companies (7.57%) had at least one published method: 34 email and 8 phone methods. Four relevant named professionals had no direct methods; there were zero direct-buyer methods. 171 companies had no usable method, and all 185 remain Research Required. Lead/Prospect coverage is N/A because those tiers had zero eligible companies. This census does not establish OK or NM coverage.

The prior no-hint stratified 20-company Firecrawl benchmark is historical context only: 4/20 companies had published methods (6 phones, 7 business emails), with no direct buyer methods. Its sample was stratified and is not a production prevalence estimate.

The census consumed 370 observed Firecrawl credits; its $1.85 reservation is a conservative replacement-cost reservation, not a measured cash charge. Worker elapsed sum was 1,376.099 seconds and enqueue-to-completion span was 1,914.534 seconds. 177 page failures are retained with reasons in the result. Actual cash billing remains UNKNOWN.

## Separate automatic follow-up

After the census, the existing automatic contact planner was enabled under a finite Firecrawl-only configuration. A later read-only observation at **2026-10-25 17:12:18 UTC** found 25/25 jobs succeeded and 25 completed Firecrawl search calls across 25 distinct company targets. There was no overlap with the frozen 185 census IDs. The follow-up produced 28 distinct email methods and 2 distinct phone methods at 2 companies, plus 3 named professionals without methods; it produced zero direct-person methods. These figures are a separate follow-up cohort and must never be added to the primary census. Counts and overlap are by canonical company ID. One follow-up record uses a distinct legacy identity associated with EOG public-domain routes; no name-based merge was made. See [automatic follow-up details](production-v12-automatic.json), which omits raw passages and biographies.

A Firecrawl credit metadata observation at 17:18:31 UTC reconciled the two phases: 2,454 credits before the production phase, 2,084 after the 185-company census, and 2,034 after the automatic follow-up. The observed total was 420 credits across 210 calls; the conservative reservation was $2.10 and actual cash billing remains UNKNOWN. The bounded manual-plus-automatic allocation is 250 calls, 210 used and 40 remaining at that observation. The global monthly ceiling is 262 calls, including 12 earlier calls for other work. No owner-unlimited Firecrawl budget, new provider, subscription, or recharge was activated. These are fixed ceilings and are not rebased by this report.

A later read-only observation at 18:12:16 UTC confirmed the next hourly planner cycle succeeded, the same images/configuration remained running, and the ledger held 235 completed Firecrawl searches. At that read, 234 contact jobs had succeeded and one remained running; no further contact-coverage census was calculated. Free credit metadata at 18:14:55 UTC showed 1,984 remaining credits, reconciling 470 production-phase credits and a $2.35 replacement reservation. The same 250-call ceiling left 15 calls at this observation. This later operational snapshot does not replace either frozen coverage cohort. See [latest bounded readback](production-v12-latest-readback.json).

## Root cause and repair

The production baseline had no published contact methods on the 185 eligible primary companies. The missing capability was automatic public discovery and a source-bound bridge from project-membership-only entities into the existing buying-chain projection. Production inventory recorded 1,154 company identities and 185 eligible customer companies. The implementation did not need a second contact database or new company identities.

Live source validation found several distinct defects repaired in the reviewed candidate: incorrect durable run persistence and unresolved work reported as complete; overly broad fax filtering and missed official-site contact navigation; a stale first project hiding a later valid company anchor; marketing text misread as a person; a discovery fingerprint changing on replay; shared retained evidence attaching a contractor to an owner; third-party directory publisher details mistaken for target-company contacts; learned URL hints changing strict request identity; and a display-date issue that let an older organization claim override a method date. Failed and rejected attempts remain documented; rejected directory-derived methods are not counted as valid coverage.

The accepted path requires source-publisher identity checks, literal method extraction, provenance and verification dates, the claim's own typed company relationship at write/read time, and existing identity continuity. Search results are hints rather than contact evidence. Provider or page failures remain unresolved and retain Research Required; interrupted paid effects remain UNKNOWN rather than prompting blind retries.

## Preservation and rollback

Read-only preservation checks at 16:59:58 and 17:09:15 UTC found all original rows unchanged across 11 protected tables, all 1,154 original company identity IDs unchanged, and zero new company identities. The pre-run count was 1,903 projects and 1,903 power needs. The checks also recorded append-only claims/evidence/identity-link counts after the census and after activation; they do not claim a general name-based duplicate detector, because company names are absent from the preserved identity model. See [sanitized preservation summary](production-185-preservation.json); it excludes row identifiers and row fingerprints.

The exact recovery dump was retained and its restore rehearsal passed. The rollback for this release is configuration/image-only and compatible with the forward schema: quiesce/reconcile bounded workers, restore the prior reviewed configuration and compatible images, then rebuild derived browse data. Do not restore the database or remove appended contact/evidence history as an application rollback.

## Release and validation evidence

The API, worker, browse, and web production images were verified against the exact release candidate; schema revision was `0041_evidence_packages`. The release canary completed at 16:21:51 UTC, normal workers resumed at 17:03:22 UTC, and the automatic worker started at 17:07:13 UTC. The Firecrawl key was present only in the private worker environment, whose file mode was 0600; the API had no Firecrawl key. Runtime settings kept `FIRECRAWL_SEARCH_V2` as the only worker intelligence contract, max active calls at 1, evaluation mode finite, and normal auto-refresh enabled.

Remote CI run `40206125623` passed its backend and browser jobs: 3,019 backend tests and 201 browser tests, with one skip in each job. Independent reviews C14, C17-R2, C18-R1, C20, C21, C24, and C25 recorded PASS for their bounded source, operational, backfill, preservation, or activation scopes. The C25 automatic-job observation at 17:09:06 UTC was an earlier partial snapshot (8 succeeded, 1 running, 16 queued); the 17:12:18 readback below records the later completed state.

Public production routing returned HTTP 200 and the protected API returned the expected unauthenticated HTTP 401. The isolated authenticated desktop/mobile contact view, method links/dates, and shared EOG case passed. **Authenticated production contact UI remains UNKNOWN** because the available Chrome session could not sign into the production account. Production UI acceptance is therefore not claimed.

## Commercial status and deliverables

Commercial P0 remains **OPEN**. There are 171/185 census companies without a usable method, no direct-buyer methods, and no authenticated production contact UI verification. Public company methods support further research but do not establish procurement authority. No OK/NM coverage, Lead/Prospect coverage, outreach, method reachability, or deliverability is claimed.

**Release recommendation:** continue the bounded released worker under its existing fixed ceilings and preserve the recovery/checkpoint controls. Keep the person-method correction in its separate reviewed candidate until its exact-head gates pass. Do not claim commercial acceptance from generic routes or test counts: authenticated production UI, qualified-company coverage and actual buying authority remain unresolved. The measured gap does not yet justify activating another paid enrichment provider.

- [Production census results (JSON)](production-185-results.json)
- [Production census company contacts (CSV)](production-185-company-contacts.csv)
- [Texas region scope receipt](production-185-region-scope.json)
- [Sanitized original-row preservation receipt](production-185-preservation.json)
- [Automatic follow-up cohort (JSON)](production-v12-automatic.json)
- [Release identity, images, timeline, budget, and status (JSON)](production-v12-release.json)
- [Later worker and credit observation (JSON)](production-v12-latest-readback.json)
- [Separate published person-method repair proof](PUBLISHED_PERSON_METHODS.md)
- [Independent production backfill review (C24)](production-backfill-review.md)
- [Independent activation review (C25)](production-activation-review.md)
- [Implementation and benchmark history](README.md)
- [Production procedure and rollback guidance](PRODUCTION_BACKFILL.md)

*This public report is a bounded v12 release snapshot. It does not certify work performed after its reviewed source candidate or close the outstanding commercial and authenticated-UI gates.*
