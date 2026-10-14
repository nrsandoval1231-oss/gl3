# California CEQAnet data-center filings

- **Publisher:** State Clearinghouse, Governor's Office of Land Use and Climate Innovation (CEQAnet).
- **Endpoint:** `https://ceqanet.lci.ca.gov/Search` with `DevelopmentType`, `StartRange`, `EndRange`.
- **Scope:** CEQA documents received in the last 60 days with an Industrial, Power or Other development type. Each search page states its document count, and the adapter fails if the table does not hold exactly that many rows.
- **Document pages:** up to 60 per run, with rows whose title names a data center read first. A filing is kept only when its title or description names a data center. The run fails if a page whose title names a data center can't be read, or if more than half of the pages fail.
- **Admission (`ceqanet-data-center-v1`):** Signal when the filing names a data center and has a received date, a link and a city or county. Moratoria, ordinances and code or plan updates are rejected. If only the description names a data center, the reason says so, because it may be one design option.
- **Real-source evidence (retrieved 2026-10-14):**
  - The Industrial search for 2026-08-15 to 2026-10-14 returned 25 documents, and the table held all 25.
  - SCH 2026020574, Elsinore Heights Industrial Project (NOP, City of Lake Elsinore, received 2026-02-13), is accepted. Its Option 2 includes one data center building.
- **Limitations:**
  - Only CEQA filings are covered. Exempt projects and other development types are missed.
  - When the window holds more than 60 documents, filings that name a data center only in their description can be missed.
  - A CEQA filing is environmental review, not construction.
  - MW, schedule and buyer are not stated.
  - This session's network blocks the host, so the evidence was gathered through a fetch proxy. The production fetch path is unverified.
