# Early-signal sources: ERCOT planning, PUCT certificate dockets, deterministic links (workstream 4a)

**Date:** 2026-11-04 · **Code:** `ingestion/adapters/early_signal_http.py`, `early_signal_stage.py`, `early_signal_link.py`, `ercot_rpg.py`, `ercot_rpg_extract.py`, `ercot_tpit.py`, `puct_ccn_dockets.py`, `puct_ccn_extract.py`, `ingestion/early_signal_state.py` · **Versions:** `early-signal-v1`, `ercot-rpg-extract-v1`, `ercot-tpit-v1`, `puct-ccn-extract-v1`, `early-signal-link-v1`

This is the first part of section 4 ("Early-signal layer") of the [ingestion handoff](../strategy/ingestion-handoff-20261103.md): the ERCOT Regional Planning Group (RPG) adapter, the PUCT certificate-docket adapter and the deterministic link between them. The Comptroller registry, Oklahoma HB 2992 notices, county abatements, water applications and Sentinel-2 change detection are a later part. It reuses the stage discipline of the [TCEQ](tceq-application-documents-20261103.md), [OK DEQ](okdeq-permit-documents-20261103.md) and [NMED](widen-document-sources-20261103.md#c-nmed) stages (shared pacer, typed `DocumentFailure`, validators, report, rest-until-`not_before`). **Everything ships off.** No deployment, credential, paid provider, migration or production data was touched, and the one-off live checks below are not evidence that anything works in production.

Rules held throughout: evidence or nothing (hash, page and verbatim quote with every value); unknown is never zero; a stated MW is a stated MW (never inferred, never site demand); documented / calculated / estimated / inferred / unknown stay distinct (no value here is `estimated` or `inferred`); at most one request per second with a declared generic user agent; no untrusted response text in any failure code, exception or index; `first_seen_at` is never rewritten.

## Live findings (read-only, 2026-11-04, scratchpad files only, nothing stored in the repository)

### ERCOT: a listing exists, files are not discovered by date path

| Target | What was found |
| --- | --- |
| `www.ercot.com/robots.txt` | Readable. It disallows `/content/...`, `/meetings`, `/widgets`, `/misapp`, `/mp/export?` and similar; `/files/docs/`, `/calendar/`, `/committees/other/rpg` and `/gridinfo/planning` are not disallowed. |
| `/committees/other/rpg` | The RPG hub: chair and list contact, the current year's meetings (17 for 2026, with reschedule notes), a "View Other Years" list (`/committees/other/rpg/2003` to `/2025`), and a short Key Documents list (planning contact list, charter). Each meeting links to `/calendar/MMDDYYYY-RPG-Meeting...`. (`/committees/tac/rpg` and `/committees/rpg` are 404s.) |
| `/calendar/07212026-RPG-Meeting` | The meeting page, with a "Key Documents" list of 16 PDFs under `/files/docs/2026/07/{16,17,20,21}/`, each with a title, a **listed date** ("Jul 17, 2026"), type and size. The files are numbered by agenda item and carry descriptive names; project IDs (`25RPG020`) appear inside the text and sometimes in the name. The October and November 2026 meetings were already listed with files (documents dated 2026-11-02). |
| `/gridinfo/planning` | Links the **Transmission Project and Information Tracking** workbook, listed as "Oct 23, 2026 - xlsx - 566.8 KB", at `https://www.ercot.com/files/docs/2022/03/02/ERCOT-October-TPIT-No-Cost-100126.xlsx`. The URL path dates from 2022 and its name from October 2026: the **file is replaced in place at one stable URL each month**, so the content hash is the only reliable change signal. An archived TPIT zip (18.8 MB) is listed separately and is not read. |
| TPIT workbook | 580,400 bytes; sheets `ImprovementCostSummary...`, `FutureTPIT100126NoCost` (1,513 rows), `PlannedTPIT...` (277), `CompletedTPIT...` (319), `CancelledTPIT...` (99), `RTPProjects`, `TransmissionOwnerProjContac`, `TSPResponsibility`, `Cost Summary Info`. The four project sheets share 33 columns: ERCOT project number, title, description, comments, terminals, status, associated projects, transmission owner, **contact (personal names and e-mail addresses)**, in-service dates, kV, circuit miles, autotransformer MVA, Mvar, county (start and end), planning tier, RPG number, RPG and board review dates, SSWG bus numbers, phase and RTP numbers. This is the "no cost" public file: **no cost column, no MW**. Of 2,208 rows, 925 are relevant (an RPG number, Tier 1 or 2, or wording about a load, customer or data center; 405 of the Future rows carry an RPG number). Titles often embed the RPG ID ("23RPG032: San Antonio South Reliability II...") and descriptions sometimes name a data-center customer ("Interconnect the Sabey Data Center load..."). 5 project numbers appear on two sheets. |
| RPG project PDFs | Text-layer PDFs. The July 2026 combined CPS Energy and STEC status update is 53 pages (3.8 MB): the first pages state, per project, the tier, estimated cost, whether a CCN is required, the in-service date and "the addition of approximately 2 GW Load". Study-assumption pages state other MW ("Approximately 980 MW of new STEC load was added in the study area") that are not project loads. The February 2026 study names the five new load stations on a slide that carries no project ID. |
| "Monthly System Planning status reports" | **No Word or Excel status report was found** on the RPG hub, a meeting page or the planning page. The only System Planning artifact found is the board deck `.../files/docs/2026/09/07/8-System-Planning-and-Weatherization-Update.pdf` (5 pages, 465 KB), which carries ERCOT-wide aggregates ($22.947 billion of RPG projects under review, $21.311 billion Large Load-dependent, $12.111 billion endorsed as of July 31, 1,114 new planning-model projects year to date) and no project rows. It is read only from owner-listed URLs. Row-level monthly change comes from TPIT. A Word parser was therefore not built and no dependency was added (see below). |

About 45 requests in all for these findings (and about 35 more in the smoke runs below), one every 1.2 s or slower, generic user agent; four 404s (three guessed ERCOT page paths and the PUCT `robots.txt`) and one 301 (the PUCT policies address) were the only non-200 answers, and none was refused or challenged.

### PUCT Interchange: no restriction found, volume counted

| Target | What was found |
| --- | --- |
| `interchange.puc.texas.gov/robots.txt` | 404: no published crawl restriction. |
| Site terms | The footer "Site Policies" link goes to the PUCT policies index (accessibility, link policy, cybersecurity and similar). Its sub-pages were **not** read; no statement about automated access was seen at the index level. The adapter's access is a handful of requests per run with the declared user agent. |
| Bot challenge | None seen on the search pages, the Excel export, the filings pages, the document pages or the PDFs. If one appears, the typed failure ends the run and nothing is bypassed. |
| Search form | The docket search takes `UtilityType`, `Description` (case style, a contains-match), `DocumentType`, `DateFiledFrom`, `DateFiledTo`, `ItemMatch` and more. `DateFiledFrom`/`DateFiledTo` bound the search to dockets with a filing in the window; the Excel export honours the same parameters and matched the page exactly in every check. |
| Documents | `Search/Filings?ControlNumber=N` lists filing items (server-rendered, paginated); `search/documents/?controlNumber=N&itemNumber=I` lists a filing's files; applications are split into PDFs of 100 pages plus a ZIP (the 509-page application for docket 59549 is 6 PDFs). Text layers are real; an OCR-quality application text has typos ("ofa", "atthe"). |

**Monthly volume (counted live).** Electric dockets whose case style contains a phrase and that had at least one filing in each month of 2026 (the phrase match alone; the adapter then also requires certificate wording):

| Month (2026) | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| "transmission line" | 25 | 24 | 29 | 27 | 22 | 27 | 29 | 38 | 36 | 35 |
| "substation" | 3 | 2 | 5 | 5 | 4 | 4 | 3 | 6 | 5 | 4 |
| Distinct dockets first seen in the year so far | 25 | 6 | 8 | 1 | 3 | 6 | 3 | 6 | 5 | 10 |

73 distinct dockets January to October; October had 35 dockets with activity, of which 6 had control numbers above 60,380 (newly opened). That is well inside a bounded run. A live listing for the shipped 60-day window returned 46 certificate dockets in 4 requests.

## Design

### Shared document stage (`early_signal_stage.py`, `early_signal_http.py`)

- **Fetch.** Exact https URL on `www.ercot.com` or `interchange.puc.texas.gov`, accepted only by a per-source path policy (exact shapes, dates validated, no query or fragment except the fixed Interchange shapes, no userinfo or port); the public DNS answer is pinned for the request (the same helper the other stages use); redirects are never followed; Content-Length and a running count cap the body; media type is checked; PDFs and workbooks are signature-checked; the declared generic user agent; the shared pacer keeps one request per second.
- **Change detection.** A conditional GET only when a stored state exists to fall back on (`If-None-Match`, else `If-Modified-Since`); a first read, a deferred read or a failed one is always unconditional, and a stray 304 with no state is retried once unconditionally. 304, or an identical hash after a new ETag, is unchanged and keeps the earlier state. Changed bytes make a new state that keeps `first_seen_at` and lists the earlier hash in `replaced_sha256`. The document SHA-256 is a line of the evidence text, so changed bytes always produce a new evidence version and the earlier one stays. Documents are only asked again after their recheck age (dated-path PDFs 14 days; the monthly TPIT workbook about daily).
- **429 / 503.** The stage stops at once; `not_before` is `Retry-After` (up to seven days) else one hour, stored in `Source.health["early_signal"]`. Until it passes the stage makes no request, and a listing 429 raises the typed error (`acquisition_code`, `acquisition_retry_after_seconds`) that the worker already classifies as transient; the service also stores `not_before` and refuses the next listing until it passes (the same service path NMED uses).
- **Failures.** Typed codes only. Permanent failures (wrong content type, wrong signature, JavaScript shell, unreadable workbook) are remembered with the hash and not retried for seven days or until the bytes change; a first 404 is also checked again after seven days. Environment failures (network, time budget) retry three times, then rest seven days. A document that was not read this run is left out of the run's records (never stored as an empty record) and the report says why; a document with a retained state keeps it.
- **Listing shrink.** The number of documents a listing names is stored in the check index; a drop to under half of the previous run's count (from at least four) is a `listing_shrink` notice, not a failure.
- **State.** `Evidence.provenance["early_signal"]` holds each document's state; `size` is the document's bytes; the check index lives in source health. Neither changes an evidence hash. No migration.
- **Reading.** PDFs through the existing killable-child text layer (`build_canonical_text`, 40 MB, 400 pages); the TPIT workbook through `openpyxl` (already a dependency) in a spawned child with a time kill, a 12 MB limit and an uncompressed-size check. **No dependency was added** (no `python-docx`: no Word file was found), so there is no `pip-audit` delta.

### ERCOT adapter (`ercot_rpg.py`, `ercot_rpg_extract.py`, `ercot_tpit.py`; source `texas-ercot-rpg-projects`)

Listing (`retrieve`, 1 request for the hub, up to `max_meetings` meeting pages that have already happened, 1 for the planning page, each checked against the job deadline; no document is read): project PDFs from the most recent meetings (agenda, minutes, charter, contact lists excluded), the TPIT workbook, and owner-listed `seed_urls` for System Planning PDFs. Each listing record carries the listed date as `publication_date` and the meeting date as `event_date`.

**Project extraction** (per page of text; every value re-derived from its own quote or dropped; quote, page and span kept; conflicting statements stay unknown and keep both quotes):

| Field | Stated shape (examples) | Basis |
| --- | --- | --- |
| project ID | `25RPG020`, `26RPG022` | documented |
| utility | segment-initial "CPS Energy submitted the ... Project (25RPG020)" | documented |
| tier | "This is a Tier 1 project" | documented |
| cost | "estimated cost of approximately $333.7 million" | calculated (scaled to dollars) |
| in-service date | "Estimated in-service date (ISD) is Summer Peak 2035" | documented |
| CCN required | "will (not) require a Certificate of Convenience and Necessity" | documented |
| load | only "the addition of approximately N MW/GW load" | documented for MW, calculated for GW; never from study-assumption sentences |
| counties | "in Bexar and Medina counties" (a preposition is required, so a project name such as "Medina County Load Project" is not a county) | documented |
| new substations | "New Castroville 345/138-kV station", "new Whitetail substation", the "New Load Stations" list | documented |

A value is attributed to a project only when its statement names that one ID, or follows such a statement on the same page before another ID appears, or the whole document names exactly one ID. Only a project-defining statement (the slide title, or "X submitted ... (ID)") switches the project; a statement that merely mentions another ID ("this project supersedes 24RPG010") ends attribution, so the bullets after it are unattributed. A stated load is also refused when its page has assumption wording (assum, study area, modeled, was/were added) or does not carry the project ID, and decimals are exact (12.5 MW stays 12.5, 1.25 GW is 1,250). Anything else stays unknown, and places named where no single ID applies are kept apart (`unattributed`) and never attached to a project. Customer names, MW per customer, load type and requested energization dates are not in RPG documents and are not produced.

**TPIT.** Relevant rows per snapshot with a row hash over the kept fields; the contact column is never read; MVA is not MW. The first snapshot is a labelled **baseline**; later snapshots yield the **monthly diff** (new, changed with the names of the changed fields, removed) relative to the previous snapshot's kept rows. Each baseline or diff row is its own observation (`ERCOT-TPIT-<snapshot hash>-<project>`), emitted **every run** from the snapshot in hand with deterministic ids and hashes (so a run that failed part-way loses no row and an unchanged re-run is idempotent), with the project's first-seen day carried across **all** snapshots in a capped map (a row that leaves and returns keeps its day). The snapshot itself is one observation (`ERCOT-TPIT-SNAPSHOT`) whose new evidence version keeps the earlier one. Its state key is the stable `tpit`, not the URL: the file is replaced in place monthly and may be re-linked under a new name, and the diff must follow it. If a lifecycle sheet read last time is missing, the read fails with `workbook_columns_changed` instead of reporting its rows as removed. Free text loses e-mail addresses and phone numbers before it is hashed or stored. Persistence time is sized as if every kept row were emitted.

**System Planning update.** Only the aggregate totals above, each with page and quote, labelled ERCOT-wide: no project, utility, county or site.

### PUCT adapter (`puct_ccn_dockets.py`, `puct_ccn_extract.py`; source `texas-puct-ccn-transmission-dockets`)

Listing: the case-style search plus its Excel export for "transmission line" and "substation" within `window_days` (default 60), cross-checked exactly (reusing `puct_docket_index.parse_search` and `parse_export`), then kept only when the style names a certificate of convenience and necessity and a transmission line or substation. Case-style facts (counties, voltage, a "new ... substation") are kept even when no document is read. Document stage: for at most `max_downloads` dockets per run, the filings list and the first PDF of the initial application and of the preliminary order (page 1 to 100 of the application only). A docket is read again only when its listing changed, a role is still unread, and seven days have passed.

| Field | Rule |
| --- | --- |
| county, voltage | from the case style, and voltage again only where the text says "new/proposed ... N kV" or "operated at N kV" (an existing line's kV mentioned in passing is not the project voltage) |
| cost | "estimated cost ... $N million" (units million, billion, thousand, M, B, K; exact decimals); a range ("to" or a dash, never "and") keeps both ends and must have low at most high; an unreadable unit ("$31.2MM") or an implausible bare figure is unknown |
| `customer_request_mw` | only the sentence shape "a customer ... submitted a request / has requested ... N megawatts" (docket 58015: "approximately 10 megawatts" with its verbatim quote, page and document hash); a sentence about generation, solar, wind, storage, injection or interconnection is refused, and two different requests (in one document or across documents) make the value unknown with both quotes |
| `stated_load_mw` | any other "N MW of load" statement, kept apart (docket 59549: "serve 129 MW of load" belongs to a different, earlier project) |
| new substations, cited RPG IDs | "new substation (the Legend Falls Substation)" only in a sentence that describes the project itself; an `NNRPGnnn` only in the project's own sentence ("this project", "the Proposed Project", "RPG review"), never next to "unlike", "supersedes" or similar |

Every value read from a PDF is stamped with that PDF's role, item, SHA-256 and URL; a case-style value has no document hash and carries the docket record's own hash and the filings URL, and links use these per-value identities, never a combined docket hash. `published_at` is the earliest filing date on the first page of the filings list once it has been read (the list is read in its default item order, so for a docket with more filings than one page this is the earliest filing seen there, not a proven first filing). Admission: the retrieval methods are in no admission set, so **no project, need or card is created** (tested).

### Deterministic links (`early_signal_link.py`)

A PUCT docket links to an ERCOT RPG project only on an exact key:

1. `substation_county`: each side must state exactly one distinct substation and one distinct county; those values must be equal after fixed normalisation (case and accents folded, punctuation removed, the words station, substation, switch, switching, new, proposed, future, tap and a voltage token dropped; at least three characters left; a bare compass name such as "North" is no key). The extractors do not preserve a relationship between multiple substation and county mentions, so multi-site or multi-county documents cannot form this key. "Rogers Road" and "Rogers Rd" are **not** equal and county alone is never a key.
2. `rpg_id`: the docket text cites a project ID that we hold.

Exactly one candidate project yields a link record (`ERCOT-PUCT-LINK-<docket>-<project>`) with the key used and the value, page, verbatim quote, document hash and URL on **both** sides. No candidate, more than one candidate project, or keys that point to different projects is **unknown** (counted as `link_unknown` / `link_ambiguous` in the stage report; no record). A link says the two documents describe the same facility; it names no customer and states no load. A link is re-evaluated every run against all held RPG projects, so a docket read before its project appears is linked when the project arrives; the record is idempotent. Jev assistance is a later consumer and is not called.

## What the live smoke showed (one-off, not proof of operation)

Real code, real httpx client, one request per second, isolated reading child, 2026-11-04.

| Check | Result |
| --- | --- |
| ERCOT listing (3 meetings) | 5 requests, 9 records (8 project PDFs dated 2026-10-16 to 2026-11-02, the TPIT workbook dated 2026-10-23). |
| CPS and STEC status update | Read in the isolated child: 25RPG020 CPS Energy, Tier 1, USD 333.7 million, Summer Peak 2035, CCN yes, 2,000 MW load (2 GW, calculated), counties Bexar and Medina; 25RPG046 South Texas Electric Cooperative (STEC), Tier 1, USD 492 million, June 2031, CCN yes, 1,000 MW; STEC counties and both projects' new substations **unknown** (the slides that name them carry no project ID). |
| TPIT | 580,400 bytes, 2,208 rows, 925 kept, baseline snapshot with 925 baseline row observations (not a diff: there is no earlier snapshot). |
| PUCT listing (60-day window) | 4 requests, 46 certificate dockets. New dockets with only a docket-number request have no application yet: case-style facts only. |
| PUCT dockets 58015 and 59549 | 10 requests. 58015: Webb County, USD 9.82 million, "approximately 10 MW" customer request quoted (application page 11 and the order), published 2025-04-28 (first filing). 59549: Medina County, USD 26.79 million to 31.15 million, stated load 129 MW kept apart as the earlier project's, customer request **unknown**, new substation Legend Falls; no RPG ID cited, so no link. |

## Limits and risks

- Project fields appear on slides that carry the project ID; substations and counties on slides without it stay unattributed, so most RPG substations are unusable for linking today (the February study's five new load stations are an example). Linking therefore needs single-project documents (project overviews and EIR scope documents often are) or a docket that cites the ID.
- Only the most recent `max_meetings` meetings are listed; earlier years exist at `/committees/other/rpg/YYYY` and are not read. Scanned PDFs are abstentions (no OCR here).
- TPIT titles and descriptions are free text from transmission owners, stored capped (160 to 300 characters) as evidence of what the row said. They may name a customer; that is a utility's statement, not confirmation.
- A docket's customer request is documented text, not a site, not demand, and not who the customer is. The preliminary order or application often does not state it (docket 59549 does not).
- Only page 1 to 100 of an application is read; later parts (testimony, attachments) are not.
- With `documents.enabled` false the ERCOT document records are withheld (a bare listing line is not evidence); the PUCT source keeps its case-style docket records, which stand on their own.
- The Windows host has no address-space cap for the reading child.
- PUCT site-policy sub-pages were not read (see above). The adapter's footprint is small; the owner should confirm the policy before enabling.
- The TPIT "relevant" filter is a judgement (an RPG number, Tier 1 or 2, or wording); a relevant row with none of these is not kept.

## What was tested

- Unit tests (no network; `MockTransport` with DNS pinned to a public address; synthetic PDFs and workbooks built from short excerpts of the public documents): URL policy accept and reject tables for both hosts (scheme, host look-alikes, ports, userinfo, queries, fragments, traversal, impossible dates, extensions, length); refusal without a request; no redirect following; private DNS refusal; one request per second; listing parse and meeting/file policy; typed 429 with `Retry-After`; JavaScript shell; wrong signature; oversize by header and by count; scanned PDF abstention; every extracted value reproducing from its own quote; conflicting statements; no cross-project attribution; study-assumption MW not taken; unknown is not zero; change detection by validators and by hash; changed bytes keeping `first_seen_at`; idempotent re-run; download budget; first-404 recheck after seven days; 429/503 `not_before`; retry back-off; permanent-failure memory; TPIT baseline, monthly diff (new, changed, truly removed, and still-listed rows that leave the relevance filter, including more than 400 changes), first-seen carry-forward, no contact data, changed columns, bad signatures, isolated child equal to in-process; System Planning aggregates; PUCT listing filter, cross-check, bot-challenge stop, customer-request sentence shape, GW conversion, cost range, voltage restriction, reread rule; link normalisation, near-name non-equality, multi-substation/county cross-pair refusal, county-only refusal, ambiguity, conflicting keys, two-sided cited-ID evidence, no peers, digest changes.
- Review regression tests (`test_early_signal_review.py`, `test_early_signal_puct_review.py`): one test per finding of the first review (cross-reference attribution, deferred-read recovery with a 304-capable origin, per-value PDF identity, request and cost parsing, TPIT missing sheet, first-seen carry, stable key, per-run rows, scrubbing, link keys, future meetings, listing shrink, deadline).
- DB-backed tests on a disposable PostgreSQL (separate schema in the `_test` database): both sources through the stage and `process_records` to Evidence with provenance, idempotent replay, no project or power-need created, the TPIT next-month diff observations with the snapshot evidence kept, ships-off `process_job` with zero requests, partial reporting without moving collection status, a stage fault as a typed error, `not_before` resting the stage across runs, a real listing 429 stored and honoured, and a PUCT docket linked to a stored RPG project on an exact key.
