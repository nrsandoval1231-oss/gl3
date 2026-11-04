# GridLens ingestion strategy

Nov 3, 2026 · @Nick Sandoval

## Executive summary

GridLens should win on two things: hearing about a project before anyone else, and turning documents into verified equipment demand. Today it does neither well. It has zero validated equipment records, and its sources are the same permits and filings competitors use. This revision adds an early-signal layer ahead of permits, fixes document fetching and table extraction, and keeps everything fast, nightly and on a capped low budget.

- **Get there first.** Trackers like Cleanview start from air permits, building permits, rezonings and utility filings. GridLens should also watch the steps before those: land-purchase notices, county abatement agendas, transmission and substation dockets, ERCOT planning submissions, water applications, new LLC registrations, and free satellite change detection.
- **Fix the demand engine.** `equipment.py` can't read tables, and adapters fetch listings instead of the engineering PDFs they link to. Build a local table extractor, then fetch TCEQ AC/TC files, Oklahoma DEQ memos, NMED applications and FERC filings.
- **Electric drives hide in prose.** Air-permit tables list emission units, so electric motors usually appear only in narrative. FERC filings state the driver explicitly, for example an 18,340 hp electric unit at NGPL Station 302 in Texas.
- **Low, capped fees.** Digital PDFs parse locally for free; scanned pages go to paid OCR; an LLM proposes values for narrative text; TypeSafe Jev runs live for matching and classification. All under gl3's dollar caps.
- **Fast nightly runs.** A one-time background backfill, then nightly runs that handle only new and changed records, with discovery split from extraction.
- **Prove it.** gl3 already records when each document was first seen. Keep that for every new source so GridLens can show it found a project before competitors did.
- **Biggest open gaps.** Texas TCEQ beyond the NSR listing was not researched, no TCEQ AC/TC PDF has been opened, and TCEQ moved new NSR documents to a JavaScript portal on Aug 31, 2026.

## Strategy principles

Every source and adapter follows the same eight rules; they come from the canon, the research and this conversation.

1. **Earliest actionable awareness beats volume.** Rank sources by how early they reveal a real project, not by row count. A land deal or substation filing is worth more than another city permit feed.
2. **Documents over listings.** A listing tells you a project exists; the linked engineering document tells you its equipment. Fetch the document.
3. **Evidence or nothing.** Every value carries a source hash, page and location. No electric drive evidence means no electrical MW; unknown is never zero; supply stays separate from demand.
4. **Deterministic first.** Rules and local tools extract and calculate; any model only proposes, and its output is verified against source text.
5. **Low, capped fees.** Local tools first; paid OCR, the LLM proposer and Jev fill gaps under daily and monthly dollar caps.
6. **Incremental and nightly.** Backfill once in the background; after that fetch only what's new or changed, timed to when each source publishes.
7. **Public and permitted only.** Official public sources and properly licensed data. Competitor databases are benchmarks, never feeds.
8. **Autonomous product, internal labels.** No routine human workflows in the product; human labeling lives in an internal gold set that measures precision.

## Get there first: the early-signal layer

To know about a project before anyone, watch the three steps that come before permits: land and company formation, incentives, and grid planning. Most trackers, including [Cleanview](https://cleanview.co/data-centers/texas), start from permits and utility filings.

&#91;embedded content: signal ladder · six stages from land deal to power-on\]

The shaded rows are where GridLens can plausibly get ahead; the lower rows are shared ground where it competes on accuracy and equipment detail instead.

**What Cleanview does (Nov 3, 2026).** 773 buildings on 252 Texas campuses, updated daily. It names air permits, building permits, rezonings and utility filings as starting sources, and satellite imagery to confirm construction. Exact capacity, tenants, online dates, utilities and sources are behind a subscription, and it has an API. It does not name ERCOT, tax abatements or news.

**Methods to borrow, not data.**

- Count buildings and group them into campuses; keep distinct physical projects separate under one company.
- Track grid power capacity and IT capacity separately.
- "Under construction" means site work has started, not an announcement. Confirm it with free Sentinel-2 imagery (10 m resolution, a new image about every 5 days) at parcels flagged by earlier signals.
- Save every source behind every record.
- Use Cleanview's public page once, manually, to check how many named Texas campuses GridLens lacks (it had 16 data-center projects at the Nov 2 release). Check their terms first; it never becomes a feed.

| Early signal | What it reveals | Access | Status |
| --- | --- | --- | --- |
| Oklahoma HB 2992 land-purchase notices | Data-center land deal within 60 days, before any permit | Notice to OCC, county and neighbors | Unknown whether OCC publishes them |
| New LLC registrations with project-style names | Developers form one company per site | Texas SOSDirect (paid per search); NM and OK business search | Feasibility unknown |
| County deed and appraisal records | Large parcel transfers to new entities | County by county | Not researched |
| County commissioners' agendas: reinvestment zones, Ch. 312 abatements | Incentive talks before rezoning | Agenda PDFs per county | Not researched; scattered |
| Texas Comptroller data-center registry; JETI | Owner/operator registrations | HTML scrape; JETI already ingested | Registry verified |
| PUCT transmission-line and substation certificate dockets | Utility plans new lines to serve a large load | PUCT Interchange | Verified examples (Dockets 59549, 58015); monthly volume not counted |
| ERCOT regional planning group submissions | Utility projects that name a large load | ERCOT RPG documents | Verified: MW totals, county, new substations, cost, dates; no customers |
| Water rights and discharge applications (TCEQ, NM State Engineer) | Cooling-water planning | Agency notices | Not researched |
| Sentinel-2 satellite change detection | Land clearing and pads at flagged parcels | Free imagery, local processing | Method only; not tested |

These sources cover industrial and oil-and-gas loads too: a new substation or water filing doesn't care what the load is.

### Grid-planning chain: from ERCOT project to substation site

ERCOT planning-group projects and PUCT certificate dockets reveal where large loads will connect and how big they are, years before energization, but not who the customers are. Checked Nov 3, 2026.

- **ERCOT planning-group (RPG) projects.** Each project has PDFs on ercot.com under dated paths with descriptive names and an ID such as 25RPG020. The [July 2026 status update](https://www.ercot.com/files/docs/2026/07/17/6.-StatusUpdate_Combined_CPS-Energy-Large-Load-Additions-Project-and-STEC-Medina-County-Large-Load-Project_July2026_RPG.pdf) shows CPS Energy adding about 2 GW of load by 2035 ($333.7M, in service Summer Peak 2035) and STEC about 1 GW ($492M, June 2031) in Bexar and Medina counties, both needing PUCT certificates. The [February 2026 study](https://www.ercot.com/files/docs/2026/01/30/8_EIR-CPS-Energy-Large-Load-Additions-Project_Updated_SCOPF_Feb2026_RPG.pdf) names five new load substations (Rogers Road, Kingsbridge, Counter Point, Whitetail, Lambda Drive).
- **What RPG documents don't give.** Customer names, MW per customer, load type, or requested energization dates. Only project totals.
- **Scale.** ERCOT is reviewing $22.9B of RPG projects, $21.3B of it dependent on large loads, and 1,114 new planning-model projects were submitted in 2026 through July ([Sept 2026 update](https://www.ercot.com/files/docs/2026/09/07/8-System-Planning-and-Weatherization-Update.pdf)).
- **PUCT certificate (CCN) dockets.** Text PDFs at `interchange.puc.texas.gov/Documents/{docket}_{item}_{id}.PDF`. [Docket 59549](https://www.cpsenergy.com/content/dam/corporate/en/Documents/Infrastructure/legend-falls-ccn/Attachment9_NewspaperNotice_ada_041726.pdf), a CPS 138 kV substation and line in Medina County ($26–32M), is "part of a larger ERCOT-endorsed project": the Medina large-load project above. Some orders state the load: [Docket 58015](https://interchange.puc.texas.gov/Documents/58015_9_1502790.PDF) (AEP Texas, Webb County) cites "a commercial customer" requesting "approximately 10 megawatts."

**Automation (free, existing gl3 patterns, no Firecrawl).**

1. **ERCOT adapter.** Collect RPG project PDFs, the monthly System Planning status reports and the TPIT report (both Word/Excel; parse locally). Extract project ID, utility, county, MW, new substation names, cost, in-service date, tier and certificate requirement. Diff monthly.
2. **PUCT adapter.** A bounded Interchange search for certificate cases mentioning transmission lines or substations, reusing `puct_docket_index.py` (search plus Excel export) and `puct_large_load.py` (filings and documents). Extract county, voltage, cost and phrases like "customer has submitted a request for approximately X megawatts."
3. **Link.** Match dockets to ERCOT project IDs by substation name and county; locate each new load substation.
4. **Find the customer.** Near each new load substation, look for land purchases, new LLCs, abatement hearings and satellite land clearing. Any customer named this way is inferred until a document confirms it.

The result is "about 1 GW is coming to these substations in Medina County" years ahead; identity still comes from the earlier rows of the ladder.

## Review of the Kimi research

The three Kimi reports (Oct 29, 2026) are worth using for evidence rules and source leads, but they are not an ingestion study and their commercial plan conflicts with the GridLens canon.

| Report | Core position | Keep | Set aside |
| --- | --- | --- | --- |
| Independent Deep Audit | Conditional go for a human-reviewed West Texas qualification service; no-go for autonomous prediction | Evidence ceiling, point-in-time snapshots, claim timestamps, merge/split history, source contract registry | Concierge workflow, accept/reject buttons, call logging |
| Equipment-Based Demand | Pivot to equipment-based MW envelopes, starting with TX/NM/OK midstream compression | hp × 0.7457 conversion, driver classification, A–D evidence grades, rating ownership, Jaguar / West Edmond / Thoreau test cases | Nothing major |
| Multi-Sector Demand | Monitor every sector; lead with data-center lifecycle plus O&G equipment | Lifecycle phases, supply ledger, managed ceilings, annual-average boundaries | Scope expansion before O&G works |

**What holds up.** Most of the evidence rules already match the canon and `equipment-demand-v1`: unknown is not zero, no electric drive means no electrical MW, standby is excluded from normal demand, supply is separate from demand, and deterministic code owns arithmetic. Spot-checked math is correct (Jaguar 6.987 MW base input, Williams 45,000 hp = 33.556 MW, the Wilson intervals).

**Where it conflicts with the canon.** The audit's commercial plan depends on users accepting, rejecting and logging leads. The canon forbids routine human workflows in the product. Keep the idea by moving it: human labels become an internal gold set for the evaluation layer, and buyer outcomes come from design partners outside the product.

**Scope drift.** The first report says stay narrow; the third says monitor everything. The canon already picked O&G first. Take the data-model ideas from the multi-sector report, not its scope.

**What's missing.** Almost nothing on acquisition mechanics: getting PDFs out of JavaScript portals, scanned documents, table extraction, amendment handling, polling cadence, cost, or terms of use. The rest of this doc fills that gap.

**Unverified claims to recheck.** ERCOT's 474 GW figure, the SPP claim that most spot loads are oil-and-gas electrification, the Riot and Galaxy numbers, and a malformed ERCOT notice link. The Williams Station 165 off-grid requirement came from a private customer call and must stay labeled as private evidence.

## Where gl3 stands today

Production (`ec6486a2`, PR165, accepted Nov 2) runs FastAPI, PostgreSQL, a durable worker and React, with 2,154 projects and a deployed `equipment-demand-v1` slice that currently has zero supported records.

| Area | Current state | Gap for demand |
| --- | --- | --- |
| Source registry | 39 entries: city building permits (Dallas, Houston, Austin, Fort Worth, San Antonio, El Paso, Albuquerque), news RSS, RRC drilling/flare/completions, PUCT and ERCOT large-load, JETI, TDLR TABS, SPP interconnection CSV, OK DEQ public review, TCEQ NSR pending, construction NOIs | Good for discovery; almost none deliver equipment schedules |
| Equipment parser | `equipment-schedule-lines-v4`: labeled line-oriented rows, exact spans, plus one FERC notice layout | Cannot read tables or general prose |
| Demand model | Deterministic Decimal hp → kW, explicit efficiency only, standby excluded, contradictions abstain, immutable receipts | Starved of inputs |
| TCEQ NSR adapter | Parses AC/TC application links; downloads only plain-language summaries for data-center/power-named filings | Engineering PDFs never fetched |
| OK DEQ adapter | Listing only; now keeps compressor-station and gas-plant rows (7 → 46 rows on one capture) | Detail-page documents not fetched |
| New Mexico | Albuquerque permits and SPP CSV only; NMED Coda pages returned 401 | APMAP, ArcGIS layers and application PDFs untried |
| Canon | Autonomous; no routine human workflows; documented / calculated / estimated / inferred / unknown amount classes | Human labeling must stay internal |

The repo already has the machinery the research recommends: immutable evidence versions, stable input fingerprints that skip unchanged extraction, idempotent replay, source health, and bounded retries. What's missing is document acquisition and table extraction, not infrastructure.

## Roadmap

Five phases, each gated by a measurable check: first make the demand engine produce records, then widen document sources, then add the early-signal layer, then cheap feeds for other sectors, and only then the fragile portals.

| Phase | Build | Output | Exit check |
| --- | --- | --- | --- |
| 1. Make the demand engine work | 20-document spike (TCEQ, OK DEQ, NMED PDFs through pdfplumber/Docling); local extraction core with span verifier and narrative driver rules; internal gold set of 50–100 permits; fetch TCEQ AC/TC PDFs for all in-scope pending filings; OK DEQ `storedpermits` memos and data-center permit page | First documented equipment claims with page and location | Spike yield measured; gold-set precision meets the gate; first validated `equipment-demand-v1` records in production |
| 2. Widen document sources | Federal Register hp/driver parser plus FERC eLibrary fetch for TX/OK/NM dockets; NMED ArcGIS facility layers plus dated application crawl; health checks for document sources | Electric motor-driven compressor records; New Mexico engine records | Each source passes gl3's readiness gate (retrieval, replay, change detection, visible failure) |
| 3. Early-signal layer | Comptroller data-center registry; PUCT transmission/substation dockets and ERCOT planning submissions, linked by substation name and county; county abatement agendas in pilot counties; OK land-purchase notices if published; water applications; Sentinel-2 change detection at flagged parcels | Projects found before their first permit | Measured lead time: days between first early signal and first permit, on a retained sample |
| 4. Other sectors and regulation | FAA OE/AAA; MSHA Mines.zip; TCEQ quarry dataset; AFDC (new host); NEVI award lists; SEC EDGAR site MW; ERCOT monthly approved-vs-observed; regulatory event feed | Discovery and phase signals for data centers, EV, mining, C&I | Unique useful projects per source; zero duplicate cards on replay |
| 5. Hard portals | BLM ePlanning, APMAP backend, Oklahoma mines notices, OK DEQ viewer, TCEQ Permit Search Portal; OCR provider switch if the bake-off favors one | Remaining permit and NEPA documents; scanned-page records | Only for documents the earlier phases can't reach |

Two research tracks run alongside phase 1: finish the Texas TCEQ track (Title V, permits by rule, Records Online, TERP, the new portal), and count monthly PUCT transmission/substation dockets and read ERCOT's TPIT and monthly planning reports (Word/Excel files not yet read).

## Per-source access, cadence and yield

Yield is a qualitative judgment from the documents inspected, not a measured rate. Verified means a researcher opened the page or file; pattern only means a URL was seen but not opened.

| Source | Sector | Access | Cadence | Key IDs | Demand fields | Yield | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [TCEQ NSR application PDFs](https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/38237-ac.pdf) | O&G, DC | GET `{project}-ac/-tc.pdf` from listing links | As listed | TCEQ project # | Engine/turbine hp, MMBtu/hr | High for engine/turbine apps (inferred) | Pattern only |
| TCEQ Title V, PBR 106.512, Records Online, TERP | O&G | Not researched | — | RN/CN | Engine hp | Unknown | Gap |
| [OK DEQ storedpermits](https://applications.deq.ok.gov/permitspublic/storedpermits/8014.pdf) | O&G | Integer enumeration of `{N}.pdf` | Per noticed draft | N, permit #, facility ID | Unit ID, hp, make/model, serial, install date | High for engines; electric only in narrative | Verified |
| [OK DEQ public review](https://applications.deq.ok.gov/PermitsPublicReview/viewpermits.aspx) | O&G, DC | HTML listing; JS document viewer | Continuous | 7-digit app ID, permit # | Via linked documents | Medium | Listing verified; viewer unproven |
| [OK DEQ data-center page](https://oklahoma.gov/deq/deq-information-on-data-centers.html) | DC | HTML table plus static PDFs | Ad hoc (Oct 28, 2026) | Permit #, app ID | Gensets, turbines (supply) | High for supply | Verified |
| [NMED air facilities MapServer](https://mercator.env.nm.gov/server/rest/services/aqb/air_facilities/MapServer?f=pjson) | O&G | ArcGIS REST, 2,000/page, JSON/GeoJSON | Unknown | AI #, permit # | Facility universe only | Discovery | Verified |
| [NMED application uploads](https://www.env.nm.gov/air-quality/wp-content/uploads/sites/2/2020/08/AQBP-Application-6567M6.pdf) | O&G | Crawl dated WordPress paths | Per notice | Permit # with M/R suffix | Table 2-A: unit, hp, make/model, dates | High for engines; electric in flow sheets | Verified |
| [NMED APMAP](https://www.env.nm.gov//air-quality/wp-content/uploads/sites/2/2021/09/AQBP-APMAP-Instructions-19.07.23.pdf) | O&G | Web app; opaque document tokens | \~1-month upload lag | AI #, permit # | Equipment lists, emissions tables | High | Guide verified; backend not |
| [NM OCD imaging](https://ocdimage.emnrd.nm.gov/imaging/Filestore/SantaFe/NF/20260413/nAUTOfCS000709_04_13_2026_02_41_43.pdf) | O&G | Dated PDF paths | Daily | OGRID, facility ID | None in sample | Entity resolution | Verified sample |
| [FERC eLibrary](https://ferc.gov/elibrary-quick-help) | O&G | Web UI, daily filings search, eSubscription email; no API | Per filing | Docket, accession # | Unit, hp, driver type | High, explicit driver | Access verified |
| Federal Register FERC notices | O&G | FR API (ingested) | Daily | Docket, FR doc # | Unit count, hp, sometimes driver | Medium-high | Verified |
| FERC Form 2 compressor schedule | O&G | XBRL download | Annual | Respondent, station | Station hp | Potentially high | Unverified |
| [EPA ICIS-Air](https://echo.epa.gov/tools/data-downloads/icis-air-download-summary) | O&G, C&I | Bulk CSV | Periodic | Program system ID | Programs only | Discovery | Verified |
| [EPA NEI 2023](https://gaftp.epa.gov/air/nei/test/where-can-i-obtain-the-2023-nei-data.html) | O&G | Regional CSV | Triennial | EIS facility ID | Gas-fired processes only | Negative evidence | Verified |
| EIA-860/860M | DC, C&I | API v2, XLSX | Monthly | Plant/generator ID | Nameplate MW (supply) | Supply only | Unverified |
| [TX Comptroller DC registry](https://comptroller.texas.gov/taxes/data-centers/data-center-lists.php) | DC | HTML scrape | Ad hoc | DC/LD registration # | Owner/occupant/operator | Discovery, entity keys | Verified |
| [FAA OE/AAA](https://oeaaa.faa.gov/oeaaa/downloads/external/content/External%20Web%20Services%20Guide%20V_2022-NOV.pdf) | DC, C&I | Keyless REST, XML, 8,000-row cap | Daily poll | ASN | Structure type (cranes), height, lat/lon, sponsor | Phase signal | Verified |
| [ERCOT monthly overview](https://www.ercot.com/files/docs/2026/10/16/ERCOT-Monthly-Operational-Overview-September.pdf) | DC | PDF | Monthly | — | Approved vs observed MW | Calibration | Verified |
| [PUCT crypto registry (56962)](https://www.puc.texas.gov/industry/electric/business/vcm) | Mining | Interchange (if public) | Annual | ESIID | 5-yr peak forecast, interruptible % | Very high if public | Public access unverified |
| SEC EDGAR full-text | DC, mining | JSON search, ≤10 req/s | Per filing | CIK | Site MW, average load | High for public companies | Unverified |
| [AFDC stations](https://catalog.data.gov/dataset/alternative-fueling-stations) | EV | API at developer.nlr.gov; CSV/GeoJSON | Daily | Station ID | Ports, connectors, planned status | Medium | Dataset verified |
| [TxDOT NEVI](https://www.txdot.gov/about/newsroom/stories/txdot-expands-electric-vehicle-charging-network.html) | EV | Results app | Per round | Site/award | ≥4 × 150 kW rule | Rule-derived nameplate | Verified |
| [EPA Clean School Bus](https://epa.gov/cleanschoolbus/awarded-clean-school-bus-program-rebates) | EV | Tables; grants downloadable | Ad hoc | NCES ID | Bus count (no fuel type) | Low–medium | Verified |
| [MSHA Mines.zip](https://arlweb.msha.gov/OpenGovernmentData/OGIMSHA.asp) | Mining | Bulk zip, pipe-delimited | Weekly (Fri) | MINE\_ID | Status, shifts, hours, portable flag | Activity proxy | Verified |
| [TCEQ quarry dataset](https://catalog.data.gov/dataset/texas-commission-on-environmental-quality-aggregate-production-operations) | Mining | Socrata CSV/GeoJSON | Updated Oct 26, 2026 | Registration # | Location, material | Discovery | Verified |
| [NM MMD registrations](https://www.emnrd.nm.gov/mmd/mmd-online-web-applications) | Mining | Export to Excel/KML | Unknown | Registration # | No equipment | Discovery | Verified |
| [BLM ePlanning](https://eplanning.blm.gov/?f=pjson) | Mining, O&G | Power Apps portal; no API | Per project | Project GUID | EIS energy, equipment | High per doc, low volume | Portal verified |
| [TEF award listing](https://gov.texas.gov/uploads/files/business/TEF_Award_Listing_Data.pdf) | C&I | One cumulative PDF | Quarterly | Company + city | Jobs, capex | Discovery | Verified |
| [Comptroller Ch. 312 databases](https://comptroller.texas.gov/economy/development/search-tools/ch311-312-reports.php) | C&I | Search pages | Ongoing | Agreement/zone | Abatement terms | Discovery | Landing verified |
| [TWDB CWSRF forms](https://www.twdb.texas.gov/financial/programs/CWSRF/doc/SFY2027/CWSRF-PIF-SFY27.pdf) | C&I | PDF lists | Annual | PIF # | Flows only (no hp/kWh) | Inferred only | Verified |
| [Dodge API](https://www.construction.com/apis/) / [IIR](https://www.industrialinfo.com/platform-and-solutions/pecweb/project-database/) | C&I | Licensed REST | Real-time | Vendor ID | Electrical specs (Dodge) | Medium, license-limited | Marketing verified |

## Terms of use and redistribution

Most government sources are public records with no stated reuse terms, so GridLens can show facts with citations; licensed and competitor data cannot be redistributed without a contract. Check each agency's site terms before production and record them in the source registry.

| Source group | Stated terms found | Working rule |
| --- | --- | --- |
| State agencies (TCEQ, OK DEQ, NMED, NM OCD, Comptroller, PUCT, OCC) | None found in the research | Public record: store, extract and cite; link to the original; no bulk republishing of whole documents |
| Federal (FERC, EPA, EIA, MSHA, BLM, Federal Register) | Generally public domain; FERC CEII and privileged filings off-limits | Use freely with citation; never touch CEII |
| AFDC station data | CC0 license | No restrictions |
| FAA OE/AAA | Public web services, no key | Use with citation |
| City open-data portals (Socrata) | Portal-specific open licenses | Check each portal |
| Sentinel-2 imagery | Free and open (Copernicus) | Use with attribution |
| Dodge, IIR, Baxtel | Licensed; terms and pricing not published | Contract required; internal QA only unless the license allows display |
| Cleanview | Paid subscription and API; terms not found on the page | Benchmark only, never a feed |
| ERCOT, regulatory PDFs | Public | Aggregates only; never present as site-level demand |

## Regulatory event feed

Rules change what a missing permit or a queue entry means, so GridLens should store them as dated events tied to geography, sector and threshold, and never silently re-read an old project under a new rule.

| Date | Jurisdiction | Event | What it changes for GridLens |
| --- | --- | --- | --- |
| Sept 21, 2026 | Texas | Governor directs TCEQ to issue no data-center permits until ERCOT and TWDB audits finish | Tag affected filings "pending — paused"; a missing permit means nothing until the pause lifts |
| Sept 18, 2026 | ERCOT | Audit survey of data centers in the interconnection queue | Expect queue revisions after audit reports (early December) |
| Aug 3, 2026 | Texas | Governor orders PUCT and ERCOT audit of data centers in the queue | Start of the audit period |
| Jul 1, 2026 | Oklahoma | Data Center Customer Ratepayer Protection Act (new 75 MW+ data-center, AI and crypto loads) and HB 2992 land-purchase notices take effect | Dedicated OCC status; possible earliest land signal |
| Jun 2026 | Texas | PUCT adopts 16 TAC §25.194: loads of 75 MW+, $50,000/MW security before study | Requested, studied, approved, energized and metered MW stay separate fields |
| Jan 2026 | SPP | FERC approves SPP's large-load process; thresholds 10 MW at ≤69 kV, 50 MW above | Applies to parts of all three states; oil-and-gas electrification counts too |
| Dec 2025 | New Mexico | PRC approves PNM contracts for Meta Los Lunas (25-00048-UT) | Example of a docket that names a site |
| Dec 2024 | New Mexico | PRC approves SPS transportation electrification plan (24-00120-UT) | Possible fleet-charging site detail |
| Nov–Dec 2024 | Texas | PUCT crypto-mining registration rule (§25.114, Project 56962) | Registry public access unknown |
| Ongoing | Texas | Project 58481 interconnection standards rulemaking; 2027 proposals for mandatory registration and ending data-center incentives | JETI and abatement signals may change in 2027 |
| Ongoing | New Mexico | Project Jupiter air permit stayed by the state Supreme Court; State Engineer pause on one well | Court and water actions are construction signals |

Dates for the 2026 Texas rule and the SPP approval come from the Kimi reports and research notes; confirm each against the docket before relying on it.

## Sector findings

Oil and gas has real equipment documents; every other sector mostly has discovery and phase signals, with equipment detail scattered in NEPA documents, SEC filings and on-site-generation permits.

### Oil and gas: driver type decides whether a record counts

- **Oklahoma memos are the cleanest state documents.** [ONEOK Ward/Northern Rows (8014.pdf)](https://applications.deq.ok.gov/permitspublic/storedpermits/8014.pdf) lists five 1,380 hp Caterpillar G-3516B and eight 2,370 hp G-3608 LE engines, all gas-fired. One unit is 1,380 hp in the memo and 1,340 hp in the conditions, so keep both values with their own spans.
- **`storedpermits` covers drafts noticed for comment, not every issued permit.** Issued permits go through Central Records. The West Edmond electric-motor example (8406.pdf) could not be re-fetched and stays unverified.
- **New Mexico hides electric drives in flow sheets.** The [Black River gas plant application](https://www.env.nm.gov/air-quality/wp-content/uploads/sites/2/2020/08/AQBP-Application-6567M6.pdf) lists four 2,250 hp Waukesha engines in Table 2-A, but "Electric Inlet Compression" appears only in the process flow sheet. The GCP-O&G form has no electric-driver fields.
- **Gas-engine records still count.** A documented gas driver is affirmative evidence the load is not grid electric: record it as a documented non-electric driver, never as zero MW or unknown. Gas units generating on-site power go in the supply ledger.
- **FERC states the driver.** The [CP24-8 order](https://aglaw.psu.edu/wp-content/uploads/2024/12/NGPL-FERC-Authorization-12.09.24.pdf) adds an 18,340 hp electric motor-driven unit at Station 302, Texas (about 13.7 MW calculated nameplate). Federal Register notices state hp more reliably than driver; [CP26-478](https://www.govinfo.gov/content/pkg/FR-2026-05-13/pdf/2026-09561.pdf) gives 11,110 hp with no driver, so fetch the filing.
- **Caveat.** Many Permian takeaway pipelines are believed intrastate, so their compressors would appear only in TCEQ permits (unverified).
- **EPA sources are supporting only.** ICIS-Air has no unit capacity fields; NEI shows only gas-fired processes; GHGRP is stalled at 2023 data with most categories proposed for removal.

### Data centers: each lifecycle phase leaves a different trace

| Phase | Best public signals (bold = not ingested today) | What it yields |
| --- | --- | --- |
| Pre-development | **OK HB 2992 land-purchase notices**, **TX Comptroller data-center registry**, JETI, Ch. 312 abatements, NM county IRBs, NM water actions | Existence, owner/operator keys, timing; no MW |
| Construction | **FAA OE/AAA crane filings**, TDLR TABS, TCEQ stormwater NOIs | Start of vertical construction; no public temp-service kW |
| Commissioning | Generator air authorizations, ERCOT approved-to-energize | A window, not a value |
| Operations and ramp | ERCOT approved vs observed, SEC filings, OCC and NM PRC contract dockets | Site MW for public companies, ramp calibration |
| Expansion | Air-permit modifications, Comptroller large-project list, FAA filings near existing campuses | Incremental phase timing |
| On-site supply | **OK DEQ data-center permit table**, NMED fuel-cell permit, TCEQ turbine applications | Supply ledger, separate from demand |

- **Texas permit pause.** On Sept 21, 2026 TCEQ was told to issue no data-center permits until the ERCOT and TWDB audits finish; applications are accepted but don't advance ([Troutman](https://www.troutman.com/insights/governor-abbott-directs-tceq-to-halt-all-data-center-permits-pending-ercot-twdb-audits/)). Some processing continued anyway ([Community Impact](https://communityimpact.com/bastrop-cedar-creek/texas-legislature/texas-continued-processing-some-data-center-permits-after-gov-abbott-s-pause-records-show/)). Tag affected projects "pending — paused", not stalled, and expect a burst of issuances when it lifts. TCEQ has also suspended at least two permits since the pause: EdgeConneX's Bastrop stormwater permit and a Google Tarrant County permit. The ERCOT audit is expected to wrap up in late November, with reports in early December.
- **Ramp prior.** ERCOT reported 9,456 MW approved to energize versus 4,132 MW observed for September 2026, about 44% ([ERCOT](https://www.ercot.com/files/docs/2026/10/16/ERCOT-Monthly-Operational-Overview-September.pdf)). Use it as an aggregate prior, never as a site value.
- **FAA matching.** Sponsors are usually crane contractors, so match filings to campuses spatially (about 2 km).
- **New Mexico.** Project Jupiter's fuel-cell permit is stayed by the state Supreme Court and its well water use is paused ([Source NM](https://sourcenm.com/?p=31964)).

### EV charging: program rules supply the nameplate

- NEVI requires at least 4 ports at 150 kW simultaneous ([ODOT RFP](https://oklahoma.gov/odot/about-us/newsroom/2026/odot-seeks-proposals-to-implement-additional-electric-vehicle-ch.html)). TxDOT Phase II awarded $226M for 321 stations on Oct 15, 2026 ([TxDOT](https://www.txdot.gov/about/newsroom/stories/txdot-expands-electric-vehicle-charging-network.html)): at least about 190 MW of rule-derived nameplate, an inferred ceiling.
- Tesla shows 19 planned Semi sites in Texas at up to 1.2 MW per charger ([electrive](https://www.electrive.com/2026/02/27/tesla-identifies-66-sites-for-proprietary-truck-charging-network/)). NM's two I-10 truck centers have 9 pull-through stalls each, kW not stated. NCTCOG publishes PDFs of funded charging projects in North Texas, and Austin's permit dataset (\`3syk-w9eu\`) can be searched for charger keywords.
- FY25 FTA bus awards in the three states fund no battery-electric buses or charging ([FTA](https://www.transit.dot.gov/funding/grants/fy25-fta-bus-and-low-and-no-emission-grant-awards)). An online Houston METRO electric-depot profile is internally inconsistent; don't use it without METRO sources.
- The AFDC publisher is now the National Laboratory of the Rockies; update any `developer.nrel.gov` URLs to developer.nlr.gov.

### Mining and remote sites: MSHA for activity, permits and filings for power

- MSHA's Mines file refreshes every Friday with status, operator, lat/lon, shifts, hours and a portable-operation flag ([MSHA](https://arlweb.msha.gov/OpenGovernmentData/OGIMSHA.asp)). Weekly diffs find new and restarted mines; shift fields give operating hours.
- Texas quarries and frac sand come from TCEQ's aggregate dataset `9ixa-7k3m` (the similar `9kvs-ig69` is stale). New Mexico MMD exports every registration. Oklahoma mine applications contain no equipment list.
- Equipment and energy detail lives in NEPA documents for federal-land mines (for example the 2026 Santa Rita/Chino amendment) and in crusher and engine air permits (not researched). BLM New Mexico's weekly decisions PDFs work as a change feed, with Federal Register BLM notices as the machine-readable trigger.
- Crypto: Texas requires sites over 75 MW to register meter ID, five-year peak forecast and interruptible share ([PUCT](https://www.puc.texas.gov/industry/electric/business/vcm)), but nothing shows the registry is public. Riot reported 700 MW approved at Rockdale with a 351 MW 2025 average, and 1 GW at Corsicana with a 335 MW average ([Riot Q4 2025](https://www.fool.com/earnings/call-transcripts/2026/03/02/riot-riot-q4-2025-earnings-call-transcript)).

### Commercial and industrial: discovery feeds now, equipment from permits and specs

- Texas has the best structured incentive data: the cumulative [TEF award PDF](https://gov.texas.gov/uploads/files/business/TEF_Award_Listing_Data.pdf) (needs table parsing), TSIF press releases, and the Comptroller's Ch. 312 and SB 1340 databases. Oklahoma's Quality Jobs dataset was last updated in 2019.
- TWDB water and wastewater forms carry flows but no hp or kWh, so any plant load from them is inferred only.
- Texas emergency engines under PBR 106.511 need no registration, so no complete public backup-genset registry exists.
- Only Dodge's licensed plans-and-specs endpoint (Division 26 electrical) offers a commercial path to equipment schedules; neither Dodge nor IIR publishes pricing or MW fields.
- Freeport LNG is likely electric-drive; Rio Grande LNG is probably gas-turbine-driven (both unverified).

## Low-fee extraction pipeline

Local tools do the bulk of the work for free; paid OCR, an LLM proposer and TypeSafe Jev handle what they can't, all under gl3's existing daily and monthly dollar caps. Every value is still verified against source text before it counts.

&#91;embedded content: extraction pipeline · text pages, scanned pages, verification\]

Text-layer pages go straight to local extraction; scanned pages go to paid OCR as soon as they're found. An LLM proposes values only for narrative passages and tables the local extractor can't parse. Nothing becomes a claim until its value is found verbatim in the page text.

**What OCR is.** Optical character recognition reads text out of an image. Digital PDFs (made from Word, Excel or permitting software) already contain their text and exact word positions. Scanned PDFs are photos of paper, so OCR has to guess each character; a blurry "1,500 hp" can come out as "1,5OO" or "7,500". That's why OCR'd values are labeled separately and never pass as native text-layer evidence.

**The stages.**

1. **Snapshot and route.** Hash each document. Record each page's character count and image coverage. Image-heavy pages with little text go to the OCR queue. Every claim records its `text_source`: native, embedded OCR, or paid OCR with provider, model and version.
2. **Canonical text layer.** Map every character offset to its word and bounding box (from the PDF, or from OCR word geometry).
3. **Deterministic tables first.** Ruled-grid pass with pdfplumber or Camelot lattice; Docling's table model as the fallback for borderless or multi-line tables. Docling and Camelot's ml mode take cell text from the PDF itself, so the model cannot alter a value ([Docling report](https://arxiv.org/html/2408.09869v5); [Camelot comparison](https://camelot-py.readthedocs.io/en/latest/user/comparison.html)). Stitch multi-page tables by repeated headers and column alignment.
4. **Narrative rules, then the LLM proposer.** Versioned phrase patterns ("electric motor-driven", "electric drive", "Electric Inlet Compression", "VFD") run first. For narrative and failed tables, extend gl3's `grounded_candidates.py` path with equipment fields: the model returns each value with a verbatim quote and page number.
5. **Normalize.** A synonym map turns headers like "EU / Unit ID / Source ID" into `unit_id`. A unit lexicon handles OCR confusions. kVA to kW needs an assumed power factor, so it is inferred. MMBtu/hr is fuel input and never becomes electric kW without a documented efficiency.
6. **Verify.** Accept a value only when it appears inside an exact text match. Fuzzy matches go to an internal review queue, never to auto-acceptance. Store the character span plus the bounding box. Jev may classify and match, but never creates or changes a value.

| Stage | Tool | Cost | Provenance |
| --- | --- | --- | --- |
| Digital-PDF tables | pdfplumber / Camelot, Docling fallback (local) | CPU only: \~0.6–1.7 s/page + 2–6 s/table | Native text bounding box |
| Narrative driver evidence | Versioned regex rules (local) | Negligible | Native span + box |
| Scanned pages | gl3's existing OpenAI vision OCR path, or AWS Textract / Mistral OCR after a bake-off | Textract tables \~$15 per 1,000 pages; Mistral OCR 4 \~$2–4 per 1,000 (third-party figure) | OCR text and geometry, labeled by provider |
| Narrative and failed tables | LLM proposer via `grounded_candidates.py` (OpenAI configured) | Per token, under caps | Verified span only |
| Matching, event class, materiality | TypeSafe Jev, live (see the Jev section) | Per call, under caps; pricing not yet researched | Advisory choice tied to evidence IDs |

**Starting caps** (gl3 `settings.py` already enforces daily and monthly call and dollar limits per provider and model): set conservative values, watch a week of spend against records produced, then raise. Exact numbers wait on Jev pricing and the spike's scanned-page share.

Paid tools only fill gaps; they never replace verification. Run a bake-off on the gold set's scanned pages (gl3's OpenAI vision path vs Textract vs Mistral OCR) and keep the one with the best field precision per dollar.

**Gold set.** An internal set of 50–100 permits, mixed by agency, digital vs scanned, and ruled vs borderless vs multi-page tables. Score field-level precision, location accuracy and abstention rate, with precision as the gate. It stays internal, consistent with the canon.

## TypeSafe Jev and going live

Jev is a decision model, not a parser: it answers typed yes/no, choice and score questions with probabilities, fast and almost free, so GridLens should use it for routing, classification and matching, never for extracting or computing values.

**What Jev is (researched Nov 3, 2026).**

- Launched in September 2026 by TypeSafe AI, whose CEO is a former OpenAI researcher ([The Decoder](https://the-decoder.com/former-openai-researcher-builds-an-ai-model-that-judges-options-instead-of-writing-text/?ref=da.van.ac)).
- API: `POST https://api.typesafe.ai/v1/systemone` with a `state` (text or object) and named `questions`: `boolean`, `choice` (up to 255 options) or `score`. Each answer returns a value and a probability ([TanStack adapter docs](https://tanstack.com/ai/latest/docs/adapters/typesafe.md)).
- Models: `jev-latest` and pinned `jev-1.13.0`.
- Vendor-reported: 70–500 ms per call; extra questions in one call add little time; $0.042 per million input tokens, output free ([AI/ML API](https://aimlapi.com/models/typesafe-jev-latest), which also lists $0.0578 and gives both 32K and 256K as context length).
- Limits: it can still pick the wrong option, it doesn't verify facts, and TypeSafe's benchmarks are self-made. Retry only on 429 rate-limit errors.

**How gl3 uses it today.** Two paths, both off in production: `signal_adjudication.py` (pinned `jev-1.13.0`, six yes/no questions on whether a Signal is a real project event) and the shadow-only `EvidenceJudge` (`jev-latest`; relevance, same-project, event type, materiality, power relevance, temporary-power hint). The call shape is right: many questions per call, probabilities validated. The gaps:

| Gap | Fix |
| --- | --- |
| Questions use the old temporary-power framing ("matter to a commercial temporary power provider") | Rewrite around demand: electric vs combustion driver in this passage, new vs existing equipment, supply vs demand, lifecycle phase, new large load or not |
| Two different model IDs | Pin one version in both paths and record it on every decision |
| Evidence cut to 1,200 characters per field | Send the full relevant passage; at these prices context is nearly free |
| Probabilities not used to abstain everywhere | Below a threshold, the answer becomes UNKNOWN |
| Unused for the new work | Add: page routing (table, narrative, scan, irrelevant) before LLM and OCR spend; PUCT docket ↔ ERCOT project matching; "does this filing describe a new large load" triage; driver-type check on a quoted passage as a cross-check on the regex rules |

**Going live, not shadow.** Live means Jev's answers act directly. Recommended authority:

- **Acts alone:** page and document routing, event-type and lifecycle labels, materiality of a change, triage of dockets and RPG documents. All reversible, with probability and model version stored.
- **Acts with corroboration:** project matching and merges. Accept when Jev is above a high threshold and a deterministic key agrees (county, substation, permit number, coordinates); otherwise UNKNOWN. The canon says a second model's agreement alone is not verification.
- **Never:** creating or changing a value, arithmetic, demand amounts.

This gives Jev more authority than the canon's current "advisory only" wording, so the canon needs a one-paragraph owner update alongside the code change.

**Activation steps.** The flags exist in `deploy/digitalocean/intelligence.disabled.env.example`; keys live in Infisical.

1. Put `TYPESAFE_API_KEY` and `OPENAI_API_KEY` in Infisical.
2. Jev: `JEV_ENABLED=true`, `INTELLIGENCE_TYPESAFE_ENABLED=true`, `INTELLIGENCE_TYPESAFE_MODEL=jev-1.13.0`, with pricing and billing fields filled and marked verified.
3. LLM: `INTELLIGENCE_ENABLED=true`, `INTELLIGENCE_OPENAI_ENABLED=true`, `INTELLIGENCE_RESEARCH_ENABLED=true`, fast and reasoning model IDs, prices per million tokens marked verified, max output tokens, `INTELLIGENCE_ENABLED_CONTRACTS`.
4. OCR: `INTELLIGENCE_OCR_ENABLED=true`, `INTELLIGENCE_OCR_VISION_ENABLED=true`, model and prices, `INTELLIGENCE_OCR_MAX_CALL_USD`, and `INTELLIGENCE_OCR_RETENTION_SOURCE_IDS` extended to the new document sources.
5. Caps: global, provider, model, source and project daily and monthly calls and USD, plus `INTELLIGENCE_MAX_CALL_USD`. All default to zero, which blocks every call.
6. Code change for live Jev: a live mode beside shadow mode, per-contract authority settings, the rewritten questions and abstention thresholds.
7. Deploy through the protected release process and watch the first night's spend and decisions.

## Fast incremental ingestion and nightly scheduling

The first load is the only slow part; after that each nightly run handles only new and changed records, which takes minutes, and the real speed limit is agency rate limits, not CPU.

**First load (backfill).** Pulling a year or more of permits means thousands of PDFs, throttled by each agency. Run it in the background over hours or days in bounded windows (for example 12 months split into validated chunks). Nobody waits on it.

**Daily volume is small.** TCEQ's whole pending NSR list was about 350 applications in mid-October 2026, so only a handful of new filings arrive per day. Oklahoma and New Mexico are smaller.

**Each cycle does more than add new opportunities.**

- **Detect changes to existing records.** Amendments, withdrawals and issuances update the existing project; a new revision is not a new opportunity. This is matching against existing records, not just skipping exact repeats.
- **Re-check listings.** Most sources don't say what changed, so fetch the listing page and diff it. That's one page, not every document.
- **Retry failures.** Documents that failed or were deferred get another attempt with bounded retries.

**How to keep it fast.**

- **Fetch a PDF only when it's new or its link changed**, and skip any whose content hash is already stored. gl3 already fingerprints extraction inputs so unchanged records are not re-extracted.
- **Split discovery from extraction.** A new filing appears immediately from listing data; equipment and MW fill in shortly after from a separate extraction queue, so slow PDFs never block new opportunities.
- **Run sources in parallel.** Most time is spent waiting on agency servers.
- **Keep OCR out of the fast path.** Scanned pages go to the background queue.
- **Use conditional requests** (ETag / Last-Modified) where a source supports them.

**Schedule.** gl3's existing scheduler, PostgreSQL job queue and worker already support this. The registry sets an interval per source (\`cadence\_hours: 24\`) rather than a clock time, and gl3 has a \`SourceScheduleEpoch\` table; check whether that epoch can anchor runs to a chosen hour, or add a run-at field. Time each source to when it publishes rather than one fixed time. All times are Central.

| Source group | When to run | Why |
| --- | --- | --- |
| Daily-publishing sources (TCEQ NSR listing, RRC nightly approved-permit files, Federal Register, MSHA on Fridays) | 3–4 AM | Overnight files are out by then; a 1 AM run can catch yesterday's file |
| Twice-daily sources (RRC pending applications) | 3–4 AM and midday | Catches the second daily refresh |
| Continuous listings (OK DEQ public review, city permit feeds, FAA OE/AAA) | 3–4 AM | One daily diff is enough |
| Slow sources (OK DEQ monthly status lists, TEF quarterly PDF, Comptroller registries, ERCOT monthly) | Weekly | Checking more often than a source publishes gains nothing |
| Extraction queue | Right after discovery, continuous | Fills equipment and MW for new documents |
| Paid OCR queue | Right after extraction flags scanned pages | Scans finish the same night, within the dollar cap |

By morning every new filing is discovered and extracted from its text layer; scanned pages are OCR'd the same night unless the dollar cap is hit.

## Source health monitoring

Document sources fail quietly: a URL can return 200 with a JavaScript shell instead of a PDF. gl3 already tracks due checks, receipts and alerts per source; extend them with document-specific checks.

| Alert | Trigger | Example risk |
| --- | --- | --- |
| Wrong content type | A PDF link returns HTML or a JavaScript shell | TCEQ's Aug 31, 2026 portal move |
| Empty text layer | A page that used to have text now has none | Agency starts posting scans |
| Extraction yield drop | Equipment rows per document falls well below the source's running median | Template or layout change |
| Zero new records | A daily source finds nothing new for longer than its normal quiet period | Silent filter or pagination break |
| Listing shrink | A snapshot listing loses an unusual share of rows | Partial page, not real withdrawals |
| Overdue | A source misses two scheduled cycles | Worker or network failure |
| Spend near cap | OCR, LLM or Jev spend nears its daily or monthly cap | Work silently stops when a cap is hit |
| Verifier rejection spike | Share of proposed values that fail the text match rises | Parser regression |

Each alert names the source, the last good run and the last good document hash, so the previous valid data stays visible while the failure is fixed.

## Proving GridLens was first

"Before anyone" is only a claim until GridLens can show when it first knew. gl3 already stores the timestamps needed (`Observation.published_at` and `first_seen_at`; `Evidence.published_at`, `observed_at` and `content_hash`), so the work is to keep them complete for every new source and measure from them.

- **Three dates per claim.** When the event happened (permit received, land deal, hearing date), when the source published it, and when GridLens first saw it. Never overwrite the first-seen time on a later refresh.
- **Lead time per project.** Days between GridLens's first signal and the first permit, the first news story, and (where checked) the first appearance in a competitor tracker.
- **Point-in-time replay.** Because evidence is immutable and timestamped, GridLens can reconstruct what it knew on any date. That supports honest backtests without hindsight leakage.
- **Retained sample.** Keep a dated list of projects with their first-signal source, so lead time is measured on a fixed denominator rather than on the best examples.

## Mapping to gl3 code

Most of the roadmap extends existing gl3 modules rather than adding infrastructure; paths are under `backend/src/gridlens/` unless noted.

| Roadmap item | Where it lands | Change |
| --- | --- | --- |
| Extraction core | `ingestion/parsers/` (new table/PDF module beside `equipment.py`, `ferc_equipment.py`) | Page router, pdfplumber/Docling tables, header and unit maps, narrative driver rules, span verifier; versioned like `equipment-schedule-lines-v4` |
| Claims into demand | `domain/equipment_claims.py`, `domain/equipment_evidence.py`, `intelligence/equipment_intelligence.py`, `domain/equipment_demand.py` | Feed verified table claims through the existing explicit conversion; keep unverified candidates separate |
| TCEQ AC/TC fetch | `ingestion/adapters/tceq_nsr_pending.py`, `tceq_http.py` | Download AC/TC PDFs for all in-scope filings, bounded per run like the summaries |
| OK DEQ documents | `ingestion/adapters/ok_deq_public_review.py` plus a new `storedpermits` adapter and data-center page adapter | Fetch memos; key lineage on permit number |
| FERC | `ingestion/adapters/federal_register.py`, `parsers/ferc_equipment.py` | hp and driver from notices; eLibrary fetch for TX/OK/NM dockets |
| New sources (NMED, FAA, MSHA, Comptroller, AFDC, PUCT dockets, ERCOT planning) | New modules in `ingestion/adapters/`; entries in `config/sources/registry.v1.json` | Same adapter interface, bounded HTTP, readiness gate |
| Discovery vs extraction split | `jobs/queue.py`, `jobs/worker.py`, `ingestion/service.py` | Separate extraction job type queued after a new or changed document |
| Nightly timing | `config/sources/registry.v1.json` (`cadence_hours`), `SourceScheduleEpoch` in `persistence/models.py` | Anchor runs to publication times |
| Health alerts | `jobs/alerts.py`, `ingestion/adapters/diagnostics.py` | Add the document-specific alerts above |
| Regulatory events | New adapter plus `LifecycleEvent` / `ChangeEvent` in `persistence/models.py` | Dated events linked to jurisdiction and threshold |
| Gold set | `backend/tests/fixtures/` and evaluation tests | Labeled permits with expected rows and locations; precision gate in CI |

Check schema needs against `persistence/models.py` before adding migrations; evidence versioning and first-seen timestamps already exist.

## Cross-cutting ingestion patterns

Snapshot every fetch, diff bulk files on their native keys, and hang amendment history and entity identity on the regulators' own identifiers.

- **Immutable snapshots.** Store raw bytes, SHA-256, URL, fetch time and HTTP validators for every fetch. Claims point at a document version, never a mutable URL.
- **Diff bulk files.** MSHA Mines.zip, the TCEQ quarry CSV, Comptroller lists, the TEF PDF, the OK DEQ data-center table and AFDC are snapshots whose value is the change. Diff on the native key and emit events (new MINE\_ID, Active → NonProducing). Don't re-ingest whole files as new evidence.
- **Page capped APIs by date window.** FAA OE/AAA caps at 8,000 rows and [Regulations.gov](https://open.gsa.gov/api/regulationsgov/) at about 5,000; re-query by modified date.
- **Amendment lineage on permit numbers, not document keys.** Oklahoma's `storedpermits` integer is a per-notice document key; the permit number (`2020-0510-TVR`, suffixes -TVR3, -M, -O) carries lineage. New Mexico encodes revisions (6567M6 is the sixth modification; P198R4 the fourth Title V revision). FERC uses docket plus accession number. A later revision supersedes for current state; both remain evidence.
- **Conflicts are two claims.** The 1,380 vs 1,340 hp case in OK 8014 is stored as two claims and flagged, never averaged.
- **Status vocabularies.** Map source statuses into GridLens-native ones with provenance, including "pending — paused" for Texas data-center filings and "approved but not observed" for ERCOT large load.
- **Polite access.** None of eLibrary, OK DEQ or NMED publish rate limits. Use at most 1 request per second, off-hours backfills and a declared generic user agent. Skip third-party scraper endpoints.

| Entity | Resolution keys | Status |
| --- | --- | --- |
| Facility | OK AQD facility ID; NM AI number; NM OCD OGRID + `fCS` facility ID; ICIS-Air program system ID | Verified |
| Mine | MSHA MINE\_ID with operator and controller IDs | Verified |
| Data center / project | Comptroller DC/LD registration numbers; JETI IDs | Verified |
| Construction filing | FAA ASN, joined spatially to campuses | Verified |
| School district | NCES ID | Verified |
| Company / plant / Texas site | SEC CIK; EIA plant ID; TCEQ RN/CN | Unverified |

## Unverified items and next research

The Texas TCEQ research is the top open item; the cheapest next step is a 20-document spike that measures real extraction yield from TCEQ, OK DEQ and NMED PDFs.

| Item | Why it matters | Status |
| --- | --- | --- |
| Texas TCEQ track: Title V, PBR 106.512 registrations, Records Online, TERP award lists, new Permit Search Portal | Largest state; intrastate Permian compressors likely appear only here | Research incomplete — top priority |
| Contents and equipment yield of TCEQ `-ac`/`-tc` PDFs | Basis for build step 3 | URL pattern seen, no file opened |
| Whether the Aug 31, 2026 portal move removes `-ac/-tc` links for new filings | How long step 3 keeps working | Unproven |
| OK `storedpermits/8406.pdf` West Edmond electric motors | The motivating electric-drive example | Could not fetch |
| OK storedpermits number range, rate limits, robots.txt | Backfill feasibility | Untested |
| OK DEQ viewer API, NMED APMAP backend, Oklahoma mines notices backend, BLM ePlanning data | Fragile-portal access | Needs browser network capture |
| FERC eLibrary stable download URLs; Resource Report 1/9/10 compressor fields | Automating FERC fetch | Undocumented / manual not retrieved |
| FERC Form 2 XBRL compressor schedule | Possible structured hp inventory | Prior knowledge only |
| Permian takeaway pipelines being intrastate | Coverage of the largest Texas compression | Prior knowledge only |
| PUCT crypto registry (Project 56962) public availability | Documented crypto peak-load forecasts | Unknown |
| OCC publication of HB 2992 land-purchase notices | Earliest data-center signal | Unknown |
| AFDC API fields and rate limits at developer.nlr.gov | EV ingestion | Docs not fetched |
| TDLR TABS fields and export; EDGAR full-text API behavior | Construction dates; SEC site MW | Prior knowledge only |
| EPA Region 6 tribal permits | NM/OK facilities missing from state systems | Not researched |
| OCC well data, RRC surface mining, NMED groundwater permits, OK/NM crusher air permits | Entity resolution and mining equipment | Not researched or blocked |
| Docling provenance schema; pdfplumber/Camelot cell boxes; Tesseract/PaddleOCR geometry and speed | Extraction implementation | Confirm in docs and by test |
| Real scanned-page share and multi-page-table frequency | Whether OCR is worth building | Not measured |
| Ch. 312 / SB 1340 export; OK Quality Jobs triennial report; NM LEDA awards | C&I discovery | Not inspected |

Open items added by the early-signal layer:

| Item | Why it matters | Status |
| --- | --- | --- |
| PUCT transmission/substation dockets as large-load signals | Possibly the earliest public utility signal | Research next |
| ERCOT regional planning submissions naming loads | Utility-side early warning | Verified examples; listing page and TPIT/status Word files unread |
| County agenda access in pilot counties | Abatement hearings before rezoning | Not researched |
| Texas SOSDirect cost and search limits for new LLCs | Entity-formation signal | Unknown; paid per search |
| Sentinel-2 change detection accuracy at small sites | Free construction confirmation | Not tested |
| Cleanview terms of use | Whether a one-off manual comparison is allowed | Not checked |
| Whether `SourceScheduleEpoch` supports clock-time runs | Nightly timing | Check in gl3 |

**Next steps.**

- [ ] Run the 20-document spike: TCEQ, OK DEQ and NMED PDFs through pdfplumber/Docling; count usable equipment rows and scanned pages
- [ ] Finish the Texas TCEQ research track
- [ ] Build the ERCOT RPG and PUCT certificate-docket adapters; first count monthly docket volume and read ERCOT's TPIT and status reports
- [ ] Add the OK DEQ data-center permit page and the Comptroller data-center registry as sources
- [ ] Capture browser network traffic for APMAP Resources links and the OK DEQ document viewer
- [ ] Update any `developer.nrel.gov` URLs to developer.nlr.gov
- [ ] Start a retained first-signal sample to measure lead time

## Sources

Kimi reports reviewed: *GridLens Independent Deep Audit*, *GridLens Equipment-Based Demand Deep Research*, *GridLens TX NM OK Multi-Sector Power Demand Deep Research* (all Oct 29, 2026). Repository: [gl3](https://github.com/nrsandoval1231-oss/gl3) at `8e13703` (canon, current state, source registry, ingestion adapters, equipment-demand slice). Competitor page reviewed: Cleanview Texas data-center tracker (read Nov 3, 2026). Source pages are linked inline in each section. Full research notes and the earlier report: *GridLens equipment document ingestion* in this project.
