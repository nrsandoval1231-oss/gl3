# San Antonio permits naming a data center

- **Publisher:** City of San Antonio Development Services, via Open Data SA (CKAN datastore). The two tables are "PERMITS ISSUED" (`c21106f9-…`) and "APPLICATIONS SUBMITTED" (`fbb7202e-…`).
- **Query:** `datastore_search?q=data center&limit=500` on each table. The run fails if the reported total is larger than the rows returned, or if any row is malformed. The project name must match "data center", and the permit must have been submitted or issued in the last 90 days.
- **Shape:** one row per trade permit type under a permit number. Rows are grouped per permit, and an issued permit replaces its application. Coordinates are kept only when they are plausible longitude/latitude; some rows are in state-plane units.
- **Admission (`san-antonio-data-center-permit-v1`):** this uses the same city rule as Fort Worth:
  - A permit becomes a Signal only when its work type is New or Addition, or it covers a substation. Trade-only rows with no work type are rejected.
  - Terminal statuses are rejected.
  - Issued permits are described as authorizing work, not as proof that construction has started.
- **Real-source evidence (retrieved 2026-10-14):**
  - SAT14 Data Center site foundation and shell, 3545 Wiseman Blvd, buildings 1–3. Issued 2026-09-29, $90.8M declared, 775,644 SF.
  - Vantage Data Center TX-22 site work, 5207 Rogers Rd. Issued 2026-02-13, so it falls outside the current 90-day window.
  - Bexar Data Center MEP trade application, 3463 Magic Dr. Submitted 2026-06-30, also outside the current window.
- **Limitations:**
  - City of San Antonio only.
  - Projects whose permit name never says "data center" are missed.
  - "Data processing center" is intentionally not matched.
  - Valuation is the applicant's estimate.
  - The data was verified through a fetch proxy; the production fetch path is unverified.
