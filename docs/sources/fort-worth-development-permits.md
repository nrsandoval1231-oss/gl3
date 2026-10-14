# Fort Worth development permits naming a data center

- **Publisher:** City of Fort Worth Development Services, via the "CFW Development Permits Table" on Fort Worth Open Data. It is an ArcGIS feature table updated hourly during business hours.
- **Endpoint:** `services5.arcgis.com/.../CFW_Open_Data_Development_Permits_View/FeatureServer/0/query`. The query is server-side: `File_Date` within the last 90 days and the work description or project name containing "data center". It returns at most 1,000 rows and fails if the service reports `exceededTransferLimit`.
- **Shape:** one row per permit and parcel. Rows are grouped by `Permit_No`, which keeps every real address and owner and drops the "FOR REVIEW ONLY" placeholder addresses.
- **Admission (`fort-worth-data-center-permit-v1`):** a new or addition permit, or a substation permit, that names a data center becomes a Signal. Remodels and renovations of an existing data center are rejected. The reason states the filed date and current status, and that a filed permit is neither an issued permit nor proof that construction has started. MW appears only when the permit text states it.
- **Real-source evidence (query retrieved 2026-10-14, files dated 2026-06-16 onward):**
  - PB26-08604 and PB26-08605: ACS Data Center DFW 12 and DFW 13, 10200 Hicks Field Rd. Each is a 283,274 GSF building with a declared job value of $327M.
  - PB26-11057: ACS Data Center Phase I substation control house.
  - PB26-11109: Edged Energy Outpost Building 2, described as a "488,628 SF 196MW data center", declared job value $300M.
  - PB26-08758: QTS FTW1 DC1 expansion, declared job value $300M.
  - PB26-13452: DFW SPE 2, a 156,866 SF data center, declared job value $500M.
  - PB26-13010: Tarrant County College renovation of an existing data center. Rejected as a renovation.
- **Limitations:**
  - City of Fort Worth only; Alliance-area parcels in other jurisdictions are not covered.
  - Permits that never say "data center" are missed.
  - Job value is the applicant's estimate.
  - This session's network blocks the host, so the evidence was gathered through a fetch proxy and the production fetch path is unverified.
