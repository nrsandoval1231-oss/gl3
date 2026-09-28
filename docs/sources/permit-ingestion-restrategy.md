# Permit ingestion strategy revision — rental, bridge and commissioning power

Date: 2026-09-27. Status: owner-authorized build direction; GL3-011 implements the first Georgia air-permit slice, with final runtime acceptance recorded in its controller receipt. Elaborates the existing ingestion strategy; does not replace the canonical PRD or its qualification gates. Existing uncommitted GL3-010 UI work is preserved.

## Decision

Prioritize power-specific official filings and follow their project lifecycle. Keep broad building permits as supporting discovery, news as supplemental enrichment, and direct procurement as a high-actionability companion. Optimize for unique projects with an evidenced rental question and a useful next step, not permit volume or card count.

The uploaded `Temporary-Power-Lead-Signals-Report.md` was read in full from the supplied ZIP. It is dated September 28, one day after this review date. Its recommendations, fleet assumptions, timings, vendor prices, market forecasts and legal claims are research inputs, not owner instructions or independently established facts. No subscriptions, account creation, contact requests or outreach were performed.

## Owner clarification: broad Signal discovery

On September27 the owner explicitly directed that opportunities such as a reported100MWcampus with20MWutility service must be visible in Signals. Unknown rental quantity, timing, duration or suitable supply must not exclude a concrete sourced project from discovery. Treat the report as accepted strategic research for source selection; the previous caution was not a Signal exclusion rule and is corrected here.

A site-bound development, proposed generator fleet, partial utility allocation, construction phase or plausible commissioning/bridge scenario can produce a Signal without proving a shortage. Show the reported campus/service values and the potential rental question. Missing information becomes a research task. Exact rentalMW remains unknown unless evidenced; Prospect/Lead gates remain distinct. A missing energization date is unknown, but does not suppress the underlying project Signal.

## What the report changes

The existing implementation collects three city building-permit feeds, with fixed commercial/building-type filters and a rolling 30-day issue-date window. It therefore misses important electrical permits, pre-issuance applications, air-permit documents and changes to older records. Broadening acceptance increased the retained permit Signals, but the recent snapshot still contains 19 permits for one event. GL3-010 groups that event in the UI; it does not provide durable cross-source project identity.

Collecting more of the same building rows is insufficient. The next capability should retrieve power-related application documents, retain their amendments, and link them to a project and a specific activity. Start before issuance; continue after issuance until the activity is completed, cancelled or supplied.

## Source priority and role

| Priority | Source family | What to collect | What it can establish | Limits |
|---|---|---|---|---|
| 1 | State/local air applications, notices, draft permits and amendments | New construction, generator additions, temporary/prime generation, operating-mode changes; equipment schedules and engineering narratives | Site, applicant, proposed generation, equipment ratings and stated operating purpose | Permanent standby equipment is not proof of rental demand; routine renewals often add no new opportunity |
| 1 | Electrical, generator, temporary-service and changeout permits | Temporary service, mobile generation, ATS/switchgear/transformer replacement, staged energization | A specific power-related activity and sometimes contractor/timing | Temporary utility service can be available supply, not a generator requirement |
| Companion | Public rental and commissioning procurement | Open generator-rental, temporary-power and commissioning solicitations, amendments, deadlines and award/cancellation notices | An explicit procurement requirement, buyer and response window where stated | Equipment purchase is not rental; load-bank-only work does not necessarily require generators; existing awards are not open demand |
| 2 | Project-specific utility/commission dockets and service agreements | Stated service dates, staged allocation, delays, substations and temporary arrangements | Corroboration of the same activity's power requirement or supply timing | Aggregate queues and generation queues cannot establish a site's load shortfall |
| 3 | Site plans, CUP/SUP applications, grading, foundation, building, stormwater | Project identity, site, stage and related permit references | Early discovery and phase progression | An approval or missing service date does not prove construction started or power is unavailable |
| Supplemental | News and announcements | Named contractor, phase, delay, energization, equipment award | Corroborating changes with attributable evidence | News volume is not independent coverage; repeat stories attach to the existing project |

Retain national, cross-industry scope. Default investigation priority remains data-center construction/commissioning, alongside explicit bridge power and continuity work at hospitals, water facilities and industrial sites. Events remain eligible; shorter duration alone is not a reason to discard them. The report's 1–500 kW fleet and unlimited paralleling assertions are not adopted as verified inventory or engineering capability.

## Initial source rollout (planning baseline)

1. **Texas air permits:** highest first-build priority, subject to access proof. TCEQ confirms its August 31, 2026 transition for specified NSR application and notice documents. Treat new portal, older NSR records and Title V channels separately. The portal returned a JavaScript shell to the text fetch: discovery is verified, automated retrieval/pagination/document access are not. Probe the supported public interface before committing an adapter.
2. **Georgia air applications and draft notices:** first fallback implementation if Texas access is unsuitable. Official program page and an actual advisory PDF were retrieved. The historical advisory identifies a data-center application, site and applicant, but says application documents may require a request. This is a format/access sample, not a fresh lead or proof that every generator schedule is downloadable. Trace current notices, draft documents and issued permits separately.
3. **Virginia DEQ:** high-priority discovery candidate for pending actions, notices and issued data-center permits. Its indexed official page was found, but direct fetch returned403. Resolve permitted access before claiming operational coverage; an issued-permit inventory alone is historical context.
4. **Existing cities' electrical/temporary-service coverage:** inspect the actual schemas and record classes before relaxing the current building-only predicates. Select one verified feed and prove new/changed/status records. Preserve existing city collection.
5. **National procurement companion:** SAM.gov API feasibility after checking availability of an owner-provided API key. Official documentation requires a key and role-dependent limits. No account or key creation implied. Use notice IDs, amendments and award status; preserve versions because the endpoint returns the latest active version.
6. **Expand by verified source yield:** evaluate other state air agencies and metro trade-permit feeds only after the first end-to-end path passes. Maintain a geography/source-family coverage matrix including unavailable and untested regions. These initial states do not constitute national coverage.

## Evidence and qualification changes

Store reported equipment separately from the activity's required power:

- Equipment count, rating value/unit, electrical versus mechanical rating, standby/prime/continuous rating basis, fuel, emissions designation, operating restrictions and source page/table.
- Project/site identity, applicant and role, parcel/address, related permit/application IDs and explicit phase/building identifiers.
- Application, publication, notice, issue, modification, retrieval and comment/response deadline dates as different fields.
- Activity: construction, commissioning, bridge service, maintenance continuity, temporary/event service, or permanent backup installation. This is an activity classification, not a replacement for Signal/Prospect/Lead.
- Buyer/contractor and role only where stated; supplier/award status, service availability and missing facts explicit.

A 40-generator standby schedule establishes reported equipment capacity, not a 40-generator rental opportunity. Do not convert bhp to electrical kW without a supported conversion basis, or kVA to kW without power factor. Do not sum incompatible ratings or count the same equipment twice across amendments. A permitted annual runtime limit is not a rental duration or proof of bridge duty.

Signals require a concrete dated project/activity event. Prospects require established activity-specific power requirements plus evidence of potentially insufficient suitable supply. Leads retain the PRD's MW, start, duration and unresolved-need conditions. Pending applications can create Signals even though they are not issued; withdrawn applications remain retained history and can close the relevant current hypothesis. Source-specific status mappings replace any blanket use of city-building statuses for air filings.

Prefer investigation order based on explicit open rental requirement, response/start deadline, actual supply-delay evidence, project specificity and known buyer role. Keep UNKNOWN separate from a poor score. Do not adopt the report's arbitrary 0–15 score or penalize all short events/small requirements by default. Ranking is separate from qualification.

## Project identity and monitoring

Use stable source+application+revision identity for observations, and supported site/project relationships for entity matching. One project may contain several buildings and distinct power needs. Address, shared consultant or registered agent alone is insufficient to merge them. Retain reasons, source references and conflicting evidence for any proposed link; ambiguous links remain unresolved.

Present one project with separately visible activities and all related permits/notices beneath it. Updates create dated events within the project rather than new cards. News corroboration joins the same evidence timeline. The GL3-010 display grouping is retained until durable matching has independently validated merge/split behavior.

For each source, perform a bounded initial backfill (proposed starting scope: 12 months, split into validated windows), then daily incremental collection. Prefer verified source modification timestamps and overlap; where absent, poll pending/open record IDs and document hashes and perform rolling reconciliation. Older issued records remain in the monitoring set while linked activities are open. Include amendment, withdrawal, award, supplied/energized and completion transitions. The present 30-day issue-date-only query must not be reused as the universal strategy.

Keep extraction separate from qualification. Retrieve listing plus linked application/narrative/schedule where accessible; retain permitted source artifacts, content hashes and page/table citations. Structured document interpretation may propose claims; deterministic validation checks units, dates, identities and qualification. Missing pages or unavailable interpretation leave retained observations pending rather than silently rejected. Reuse the existing durable worker and job system; no new orchestration platform is needed.

## Corrections to the report

- Air applications are valuable technical evidence, but the report does not establish that they universally precede equipment ordering or that every temporary deployment leaves an accessible notice.
- Fixed lead-time ranges are hypotheses for prioritization, not project-specific start/duration facts.
- Its 9.0 GW divided by238.6 GW example is about3.8%, not1.6%; approval to energize is also not the same as operating load. Do not import that conversion statistic.
- A100MW campus with20MW utility service has no determined rental requirement without the same activity's demand, timing and other suitable supply. Show this opportunity in Signals with100MWcampus capacity and20MWreported utility service. Label bridge service as a hypothesis for research; do not populate an exact rental requirement from those two values alone.
- Generator fleet size, load-bank demand and permitted runtime are distinct from rental generation demand.
- Missing energization information remains UNKNOWN. Keep the concrete project visible as a Signal and flag utility timing/possible bridge service for research; do not require confirmed demand to admit it.
- Do not deanonymize an owner from a registered agent or consultant match alone. Do not assume every campus will become a rental customer.
- Vendor coverage/prices, aggregate queue waits, equipment lead times, regulatory interpretations and market forecasts were not comprehensively audited. They are not prerequisites for the revised ingestion design.

## First build and acceptance sequence

**A. Source access proof:** validate current Texas listing/document retrieval; if inaccessible, proceed with Georgia rather than inventing a working feed. Retain real applications, amendments, renewals and withdrawals where available, with honest sample gaps. No source enabled until retrieval and retention are permitted and reproducible.

**B. One vertical end-to-end slice:** implement one state's applications/notices into existing durable observations; parse available equipment details and publish source-bound Signals. Do not force a new Signal when only historical renewals are available. Demonstrate ordinary-worker execution, retained attachments, replay, changed-document history and visible failures.

**C. Identity and lifecycle:** prove that notice/application/amendment documents for the same project do not inflate cards, while distinct buildings and activities remain separate. Recheck older active applications and close only the supported activity on withdrawal/supply completion.

**D. Add explicit electrical/temp-service discovery, then procurement:** prove one useful feed at a time, preserving project links and negative evidence. Expand state/geographic coverage from measured unique useful project yield rather than adding empty registry entries.

Acceptance measures: newly discovered unique projects; new material events on existing projects; distinct power activities; explicit rental/bridge inquiries versus context-only records; source citation coverage; review precision with stated sample denominator; unresolved-duplicate rate; source lag; pending document/interpretation backlog; successful older-record change detection; no duplicate creation on replay. Maintain region and source-family coverage counts separately. No invented target signal count or accuracy percentage.

## Verification sources

Checked September27,2026; these verify source existence/access characteristics, not production ingestion readiness.

- [TCEQ pending air permit information](https://www.tceq.texas.gov/permitting/air/airpermit-applications-notices): transition date, document scope and separate TitleV channels verified. [Portal](https://permit-search.tceq.texas.gov/) needs further access validation.
- [EPA data-center Clean Air Act resources](https://www.epa.gov/stationary-sources-air-pollution/clean-air-act-resources-data-centers): state/local authority and equipment/regulatory resources. Not a project lead feed or blanket legal conclusion.
- [Georgia air permitting program](https://epd.georgia.gov/air-protection-branch/air-branch-programs/permitting-program) and [historical public advisory](https://epd.georgia.gov/document/document/pa1224-4/download): actual named application and document-access limits inspected; January2025 deadline is historical.
- [Virginia issued data-center air permits](https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers): official indexed listing found; direct retrieval403, readiness unverified.
- [SAM.gov public opportunities API](https://open.gsa.gov/api/get-opportunities-public-api/): key, pagination, latest-active-version and refresh behavior checked.
- [ERCOT large-load integration](https://www.ercot.com/services/rq/large-load-integration): use load-specific records; project-level named access requires separate proof.

Build update: GL3-011 adds the Georgia EPD current Draft Title V list with required narrative/draft PDF extraction and broad discovery Signals. Texas public search access is proven, but document retrieval and an operational adapter remain pending. See `georgia-air-permits.md` and `.agent/artifacts/GL3-011/` for the implemented scope and validation. National coverage remains open.
