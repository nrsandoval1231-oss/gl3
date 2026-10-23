# Texas power sources — October 23, 2026

Checked against public endpoints on October 23, 2026. A 200 response was not treated as a parse success. Registry rows are the enabled definitions. This note does not claim a scheduled production run.

The ranking followed the behind-the-meter, bridge, and temporary-power source notes. A generator, turbine, or filing is tagged `btm`, `bridge`, or `temporary` only when its own text uses that language.

## Ingested

| Source | Agency | URL | What a row yields | Signal tags |
|---|---|---|---|---|
| `texas-puct-large-load-filings` | Public Utility Commission of Texas | Filings page `https://interchange.puc.texas.gov/Search/Filings?ControlNumber=59142`. Excel export `https://interchange.puc.texas.gov/search/exportfilings/?ControlNumber=59142&ItemMatch=0&SortBy=ItemNumber&SortOrder=Ascending` and the same export for control number 58481 | One row per filing: control number, item, file stamp, party, and description. The item-document URL is the citation. A place is recorded only when the filing text names one. | `btm`, `bridge`, or `temporary` only from the party or description |
| `texas-tceq-egu-registrations` | Texas Commission on Environmental Quality | Search form `https://www2.tceq.texas.gov/airperm/index.cfm?fuseaction=airpermits.start`, posted to `https://www2.tceq.texas.gov/airperm/index.cfm` | Pending standard permits for unit 8340 (electric generating facilities) and unit 15627 (natural gas electric generating units), and pending permit-by-rule rows for unit 7644 (engines and turbines). Near city and county become the place. The received date is the event. | Same three tags, only from the row text |
| `texas-jeti-applications` | Texas Comptroller of Public Accounts | `https://api.comptroller.texas.gov/open-data/v1/tables/jeti` (the table loaded by `https://comptroller.texas.gov/economy/development/prop-tax/jeti/applications.php`) | Applicant, school district, application or created date, and links to posted PDFs under `https://assets.comptroller.texas.gov/open-data/jeti/`. | Same three tags, only from the applicant or district text. No site is invented, so these rows stay evidence |

## Checked and not ingested

| Source | Why it was skipped |
|---|---|
| ERCOT large-load interconnection queue | `https://www.ercot.com/services/rq/large-load-integration` is the forms and template hub (RFI PDFs and Batch Zero spreadsheets). It is not a project queue. The monthly Large Load Interconnection Status deck changes URL, so there is no stable machine-readable queue to pin. PUCT 59142 and 58481 are the stable filing records. |
| TCEQ construction stormwater TXR150000 | `https://www2.tceq.texas.gov/wq_dpa/` is a search form. The page itself has no result table and no export. |
| TDLR TABS | `https://www.tdlr.texas.gov/TABS/Search` is an ASP.NET search form. The existing TABS source stays disabled. No export was added. |
| Additional Texas city or county building permits | Austin, Dallas, Houston, Fort Worth, San Antonio, and El Paso already have adapters. No further county open-data permit URL was verified for this change, so none was added. |
