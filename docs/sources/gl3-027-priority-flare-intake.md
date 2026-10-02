# Priority geography and flare permit intake

Owner direction, October 1, 2026: prioritize Dallas, Austin, Houston, El Paso and California. Prioritize data-center construction temporary power, then data-center commissioning temporary power, then oil and gas temporary power. Keep all other national/industry sources enabled. This is acquisition prioritization, not a new runtime ranking algorithm.

## Existing priority coverage

- Dallas: enabled published monthly commercial new-construction workbook adapter. Does not establish citywide electrical/generator permit coverage.
- Austin: enabled commercial building/electrical Socrata feed with rolling issue/modified windows and explicit bounded data-center/power backfill.
- Houston: enabled four-report weekly sold-permit adapter and exact sold-permit detail enrichment. Sale events remain distinct from current lifecycle status.
- El Paso: enabled NewCommercial GIS layer, rolling 90-day issue window with count-checked paging. Does not establish citywide electrical coverage.
- California: priority source onboarding remains a gap. Official CEC data-center/backup-generation proceedings, San Jose planning applications and CalGEM data routes have been discovered; these are not enabled feeds. Backup capacity is not an activity-specific construction or commissioning load.

## Verified flare ingestion

The RRC official public route is https://webapps.rrc.state.tx.us/swr32/publicquery.xhtml, linked by https://www.rrc.texas.gov/news/021622-flaring-query/ and its published query guide. It covers electronically submitted Rule 32 exception applications from May 2, 2021 onward, not all flaring authorizations or actual flare measurements.

The enabled adapter retrieves the current and prior two Texas calendar days by submittal date, using the anonymous public form and normal JSF paginator. It checks the advertised count, row offsets and distinct filing numbers, with 10 rows per page, at most 50 pages/500 records, 2 MB per response and 20 MB per run. Exceeding a bound or receiving incomplete pages fails visibly before persistence. The ordinary job retry/fencing and last-good retention rules apply.

Actual October 1 Texas-date acquisition retained all 38 filings submitted September 29–October 1, 2026. Immediate replay returned all 38 unchanged; observations, evidence, projects, power needs, links, buying-chain claims and interpretations were exactly unchanged. Filing number anchors identity across status/date changes. Submittal, authorized effective and expiration dates remain separate; no publication date is invented. The historical query total of 21,470 is not the adapter's coverage count.

Examples include DIAMONDBACK E&P LLC filing 35895 and its commingle-permit property labels. Operator is the source-listed role, not a verified buyer. Records appear in Ingestion under Oil & gas and the RRC flare source. List records do not create physical projects or Signals; exact flare/well location and a supported power activity remain unverified. Application details, attachments, historical backfill and later status changes to filings outside the three-day submittal window are not acquired. Local auto-refresh remains off; this validation proves actual checks and replay, not unattended daily operation.

Flare/vent authorization records do not establish recoverable gas, sustained flow, composition, fuel suitability, generator capacity, an open rental package or buying authority. Keep source roles, authorization status, applications and dates distinct. No other source is disabled by these priorities.
