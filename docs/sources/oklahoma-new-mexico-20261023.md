# Oklahoma and New Mexico sources — October 23, 2026

Checked against public endpoints on October 23, 2026. A 200 response was not treated as a parse success. Registry rows are the enabled definitions. This note does not claim a scheduled production run.

## Ingested

| Source | Agency | URL | What a row yields | Signal tags |
|---|---|---|---|---|
| `oklahoma-deq-public-review` | Oklahoma DEQ | `https://applications.deq.ok.gov/PermitsPublicReview/` | Current public-review table rows that name a data center, power plant, turbine, generator, or engine. County becomes `County, OK`. A comment-window start is kept only when the step text states one. | `btm`, `bridge`, or `temporary` only when that language is in the row |
| `spp-thermal-interconnection` | Southwest Power Pool | `https://opsportal.spp.org/Studies/GenerateActiveCSV` | Oklahoma and New Mexico thermal or gas generator-interconnection requests, plus any row that names a data center. Capacity stays generation-injection MW. | Same three tags, only from row text |
| `albuquerque-building-permits` | City of Albuquerque | `https://data.cabq.gov/business/buildingpermits/BuildingPermitsCABQ-en-us.csv` | Building permits issued in the last 730 days that name a data center, or commercial permits that name a generator, turbine, or explicit temporary, bridge, or behind-the-meter power | Same three tags, only from the description |

Wind, solar, and storage-only SPP requests are not emitted. Undated Albuquerque rows are not emitted. Oklahoma DEQ detail pages are not fetched.

## Checked and not ingested

| Source | Why it was skipped |
|---|---|
| Oklahoma Corporation Commission utility dockets | `https://oklahoma.gov/occ/divisions/public-utility.html` and `https://public.occ.ok.gov/` are HTML brochure or portal pages. No stable machine-readable docket export was found. `https://imaging.occ.ok.gov/` returned 404. |
| New Mexico Environment Department Air Quality Bureau current actions and issued NSR | The permitting page points at Coda documents (`coda.io` / `docs.superhuman.com`). The public Coda API returned 401, and the page itself is a script shell rather than a table or file. |
| New Mexico Public Regulation Commission | `https://www.prc.nm.gov/utilities/` is HTML. `https://edocket.prc.nm.gov/` failed the TLS handshake. No machine-readable case export was found. |
| Oklahoma open-data catalog search for air permits | `https://data.ok.gov` package search did not return a DEQ air-permit dataset. |
| New Mexico Environment Department public-notice page | `https://www.env.nm.gov/public-notices/` mixes every program and links PDFs. It is not a permit table. |
