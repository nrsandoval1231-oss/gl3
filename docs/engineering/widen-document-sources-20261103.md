# Widening document sources (workstream 3)

**Date:** 2026-11-04 · **Code:** `ingestion/parsers/permit_docs/notice_hp.py`, `notice_post_rating.py`, `adapters/ferc_elibrary.py`, `adapters/nmed_http.py`, `adapters/nmed_air_facilities.py`, `adapters/nmed_application_documents.py`, `ingestion/nmed_document_stage.py` · **Versions:** `fr-notice-hp-driver-v1`, `nmed-air-facilities-v1`, `nmed-application-document-v1`

This is section 3 of the [ingestion handoff](../strategy/ingestion-handoff-20261103.md): Federal Register hp and driver evidence, FERC eLibrary, and New Mexico (NMED). It reuses the [1a extraction core](permit-document-extraction-20261103.md), the shared pacer, typed failures and report from the [TCEQ stage](tceq-application-documents-20261103.md), and the [OK DEQ](okdeq-permit-documents-20261103.md) state and rest-until-`not_before` pattern. **Everything ships off.** No deployment, credential, paid provider, migration or production data was touched, and the one-off live checks below are not evidence that anything works in production.

Rules held throughout: evidence or nothing (hash, page and location with every value); no stated electric drive means no electrical demand; unknown is never zero; supply stays apart from demand; at most one request per second with a declared generic user agent; no FERC CEII, ever.

## Live findings (read-only, 2026-11-04, a few polite requests, files kept outside the repository)

| Target | What was found |
| --- | --- |
| `elibrary.ferc.gov` | `robots.txt` is a 404. `/eLibrary/search` and `/eLibrary/docketsheet` return the same 22 KB Angular shell (no data). The shell's `assets/config/app-settings.json` names an internal service (`/eLibraryWebAPI/api/`) with a client token embedded in the public script; the script also contains group checks for non-public and CEII access. FERC documents no API for it. |
| `www.ferc.gov` | `robots.txt` readable. Its RSS and eSubscription help pages answered **403 with a Cloudflare managed challenge** ("Just a moment", needs JavaScript and cookies). Not bypassed. No FERC RSS or feed URL could be confirmed. |
| `mercator.env.nm.gov` | The handoff path `/arcgis/rest/services/...` is a 404; the live base is `/server/rest/services`. `aqb/air_facilities/MapServer` has seven layers (details below), `maxRecordCount` 2000, formats JSON, geoJSON and PBF, `resultOffset` paging supported. |
| `www.env.nm.gov` | `robots.txt` disallows only `/wp-admin/`. The WordPress media REST endpoint of the air-quality site lists only **5 PDFs** in total (none are applications); application PDFs are not in that library. A known application upload (`.../sites/2/2020/08/AQBP-Application-6567M6.pdf`) answers HEAD with 200, 7.6 MB, an ETag and `Last-Modified`. `https://www.env.nm.gov/public-notices/` (1.3 MB HTML, 747 PDF links) links 54 PDFs under the air-quality uploads, 10 named as applications, newest upload month 2025-07. |

### NMED facility layer schema (verified)

Layers: 0 Major-Title V (131 rows), 1 Minor (490), 2 Synthetic Minor (2,409), 3 No Permit Required (399), 4 Notice of Exemption (86), 5 Notice of Intent (3,416), 6 Nonactive (2,745). All seven have the identical twelve fields: `OBJECTID`, `AI_NAME`(100), `PHYSICAL_ADDRESS_LINE_1`(100), `MUNICIPALITY`(31), `COUNTY`(31), `STATE`(2), `ZIP`(9), `AI_STATUS`(31), `AI_TYPE`(63), `FACILITY_CLASS`(31), `LAT`, `LON`; point geometry in WGS84. `AI_TYPE` values on layer 0 include `O&G-Compressor Station`, `O&G-Refinery`, `O&G-Gas Plant`, `O&G-Production Facility`, `O&G-Loading/Unloading Rack`, `O&G-Tank Battery/Bulk Fuel Storage`.

**There is no AI number and no permit number in the public layers**, contrary to the strategy note. The facility identity is name, address, county and layer; `OBJECTID` is a layer-local key that ArcGIS does not promise stable across republishing. There is also no date field.

## A. Federal Register hp/driver evidence

`extract_notice_hp_driver(excerpt)` reads the bounded text that `govinfo_pdf.retrieve_companion` already builds (`[GovInfo PDF page N] ...`). It uses the 1a narrative rules, lexicon and exact-span verifier unchanged for the "N-hp electric compressor motors" shape, plus one extra shape in `notice_post_rating.py` for the form Federal Register FERC notices actually use: `Install one new electric motor driven compressor unit with a rating of 18,340 hp`. Every field of the post-rating shape goes through the same `_span_problem` and `_recompute_problem` checks (quote at its span, value recomputed from the quote alone), and a rule keeps the rating in the equipment's own phrase (same sentence, same page, short gap).

- **Electric must be stated.** `electric_demand_evidenced` is true only for an electric driver quote in the rating's phrase on a compressor, pump or motor row in hp, kW or MW that is not retired. A rating beside a combustion driver, or with no stated driver, is `supply_other` with `drive: unknown`.
- **West Edmond-style trap.** A driven compressor's rated hp is never turned into the motor's rating: "three 5,200-hp Ariel compressors" is supply with unknown drive; "2,500-hp electric compressor motors" is a separate row. Uprates ("increase the horsepower of existing Units 7 and 8 by 1,600 hp each"), re-wheels and thresholds ("greater than 1,000-hp") match nothing.
- **Evidence.** Each row keeps the verbatim quote, the PDF page and the character span inside `Evidence.abstract`, re-checked against that text before the row is returned. A repeated mention is one unit. No row means an explicit abstention, never zero.
- **Wiring, flag off by default.** `query.hp_driver_evidence` (boolean, allowed on `federal-register-eis` only) makes the companion fetch add `hp_driver` to its citation and the service store it as `Evidence.provenance["fr_hp_driver"]`. With the flag absent or false the call, the evidence row and the interpretation are exactly as before (tested). Not retroactive: evidence is immutable and keyed by PDF hash.
- **On the retained real notice** (`FR-2024-12869`, Compressor Stations 302 and 343) the parser returns exactly one row: compressor, electric, 18,340 hp, count 1, proposed, with quotes from page 2. The CS343 re-wheel and the Units 7 and 8 uprate produce nothing. MW is not computed: the existing native path deliberately leaves quantity unknown, and this block only supplies hp and driver evidence.

Limits: only the two shapes above; "horsepower (hp)" parentheticals and ratings in tables inside notices are not read; scanned notices (OCR path) are not read; the notice does not say the unit is built or running.

## B. FERC eLibrary

**Finding: no compliant machine-readable path exists, so nothing is fetched.** FERC publishes no API or feed for eLibrary. The public pages are a JavaScript shell over an internal service that needs a token taken from the page's own script, FERC's other site is behind a bot challenge, and the same application contains non-public and CEII access groups. Calling the internal service or evading the challenge is not a documented public path, and the CEII risk is not worth taking. No fake coverage is claimed and no registry source was added.

What exists (`ferc_elibrary.py`, no network code at all, tested with sockets disabled):

- `reject_nonpublic(*values)` raises `NonPublicRejected` for any CEII, critical energy/electric infrastructure, privileged, non-public or protected-material marker, in a URL or in free text. `is_public_elibrary_url` accepts only `https://elibrary.ferc.gov/eLibrary/docketsheet?docket_number=CPyy-n[-sss]` and `/eLibrary/filelist?accession_number=<14 digits>`, rejecting the API path, other hosts, extra parameters, userinfo and fragments.
- `docket_references(docket_context)` turns a docket a notice already states, in its SOURCE_BOUND context (the same context the native FERC path builds), into a reference to the public docket-sheet page for a person to open (`access: reference_only_not_fetched`). Only CP dockets; a conflicting, missing or UNKNOWN docket gives nothing. It is not wired into any output yet.

Open: if FERC ever documents a feed, or the owner approves eSubscription email intake with its own consent and CEII-safe handling, the adapter would be built around that. A parser could not be fixture-tested because no public machine-readable sample could be retrieved.

## C. NMED

### Facility layers (`nmed_air_facilities.py`)

A bounded, read-only reader for the seven layers. Fixed query shape (explicit field list, `returnGeometry=false`, `orderByFields=OBJECTID`, `resultOffset` paging, optional `AI_TYPE LIKE 'O&G%'`), exact host and path, DNS pinned, redirects never followed, at most one request per second, 5 MB per response, at most 30 requests and 10,000 records per run, the first 429 or 503 ends the run with `Retry-After` reported. A layer that stops at a cap or error is marked `truncated`; a full page is followed by one more request so completeness is only claimed on a short page. Coordinates outside New Mexico become unknown (both), strings are control-character-stripped and length-capped, and `ai_number` and `permit_number` are `null` with an explicit `identity_basis`.

It is **not wired to a registry source or job**: the layers have no date and no join key, so ingesting them as observations would create dateless records that cannot be joined to a document. It exists as the identity/coordinate universe a later join (county plus name, reviewed) can use.

### Application documents (`nmed_application_documents.py`, source `new-mexico-nmed-air-applications`)

Discovery is the NMED public notices page (one request, at most 3 MB), whose links are filtered by an exact upload-path policy (`https://www.env.nm.gov/{air-quality/wp-content/uploads/sites/2|public-notices/wp-content/uploads/sites/32}/YYYY/MM/<name>.pdf`, no query, fragment, userinfo, port, traversal, or archive host) and a name filter (contains "application"; not approval, letter, hearing, notice-of, spanish, transmittal, comment), plus an owner `seed_urls` list (at most 50). Records are dated only by the upload month: `publication_date` is the first of that month with `publication_date_precision: month`, and the application date, applicant and facility are not read from the listing.

The stage follows the TCEQ and OK DEQ discipline:

- HEAD, then a conditional streamed GET with a running SHA-256 (never in memory), 40 MB cap by Content-Length and by count, `application/pdf` only, first bytes `%PDF-`, HTML is `js_shell`.
- Change detection: same ETag (or same Last-Modified and length) is unchanged and skipped; a new ETag with identical bytes is unchanged by hash; changed bytes make a new state that keeps `first_seen_at` and lists the earlier hash in `replaced_sha256`. The document SHA-256 is a line of the evidence text, so changed bytes always yield a new evidence version while the earlier one stays.
- Isolated child extraction by the 1a core with a sub-deadline (job deadline minus a persistence reserve; no HEAD with less than about 70 s left, no download with less than 150 s left).
- A 429 or 503 stops the stage at once and stores `not_before` (Retry-After, else one hour) in source health; until it passes the stage makes no request. Permanent failures are remembered with validators and hash and not fetched again until they change; environment failures retry three times, then rest seven days unless the validators change. No exception text or response content is stored, only codes and small integers.
- Supply (no stated electric drive, and every generator, engine or turbine) is kept in provenance apart from demand; a document with no verified schedule is an explicit abstention (`zero_verified_rows` is a notice, not a failure).
- State lives in `Evidence.provenance["nmed_document"]` and the check index in `Source.health["nmed_documents"]`, so a re-check never changes an evidence hash. No migration.

Limits and risks:

- The notices page is a thin source: about ten application files, the newest uploaded in 2025-07. Most applications (for example the Black River application in the research note) are reached only through owner `seed_urls`.
- No facility join. Without an AI or permit number in the public data the application cannot be tied to a facility, and nothing is guessed from file names.
- **No NMED admission rule exists.** The records are retained evidence; they do not create demand, needs or cards. Electric inlet compression is often stated only in a process flow sheet, which no extractor reads, so many applications will be abstentions.
- Scanned pages are counted and not read (OCR is out of scope here). The Windows host has no address-space cap for the reading child.
- Dates are month-precision upload paths only.

## What was tested

- Unit tests (no network; MockTransport with pinned DNS, fake-clock pacing, synthetic text PDFs): hp/driver rows and traps (rating without driver, combustion driver, motor versus compressor ratings, removal, thresholds, uprate and re-wheel bullets, repeated mention, multi-page citation, abstentions) and the flag plumbing through `retrieve_companion` and registry validation; FERC policy (36 cases: CEII and privileged markers in URLs and text, exact URL shapes, docket derivation, no sockets used); NMED facility layers (fixed query shape, host policy, paging, caps and truncation, record normalisation, coordinates, 429 and 503, error payloads, bad replies, oversize, deadline, one request per second, config bounds); NMED documents (URL policy, listing parse and filters, month-only dates, one-request listing, seeds, response cap, registry bounds, extraction with demand and supply, abstentions, the real isolated child, change detection by validators and by hash, changed bytes, idempotent fold, budgets, oversize by header and by stream, one request per second, bad content types and signatures, redirects, 404, failure never replacing an accepted document, 429 and 503 with `not_before`, retry back-off).
- DB-backed tests on a disposable PostgreSQL (separate schema in the `_test` database, Docker container removed afterwards): the retained real GovInfo notice with the flag off (no block, unchanged call) and on (one verified row, quotes at their spans, evidence otherwise identical); a synthetic NMED application through the stage and `process_records` to Evidence with provenance, idempotent replay, changed bytes keeping the earlier evidence, generator-only abstention, ships-off `process_job` with zero requests, partial reporting without moving collection status, a stage fault as a typed error, a rate-limited listing making no requests, and `not_before` resting the stage across runs through source health.

## One-off live smoke (not proof of operation)

See the section appended below by the live run.
