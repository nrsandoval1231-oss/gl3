# TCEQ pending New Source Review air permit applications

Source ID `texas-tceq-nsr-pending`. Statewide Texas. Added October 14, 2026.

## What it is

The [official listing](https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/nsr-pending-permits.html) of pending case-by-case NSR applications: applicant, facility, permit numbers, received date, application stage and a stable TCEQ project anchor. For filings whose names indicate data-center or power-generation activity, the bounded Plain Language Summary PDF (`{permit}-pls-english.pdf`) supplies the regulated entity, site sentence (city, county, often coordinates) and the stated purpose.

Checked October 14, 2026: 353 listed applications. Data-center or on-site generation filings included Crusoe Energy Systems (Longhorn and Goodnight data centers), Aligned Data Centers (ADC Plano), Fermi America (Project Matador), Nexus Data Center Hubbard and VoltaGrid (ABI-1). The Longhorn summary states "power generation equipment for onsite consumption in data center buildings" at Abilene, Taylor County.

## Admission

A row becomes a Signal only with data-center or on-site-load context, a site from the summary, a received date and the official link. Merchant or industrial generation without stated on-site load stays evidence: a generating asset is not automatically a load-side rental opportunity.

Proposed onsite generation is **proposed supply**. It does not answer the power gap. The Signal's question is whether construction or commissioning needs temporary power before permitted onsite generation or utility service is available. MW, start, duration, buyer and authority stay unknown.

## Limits

- Pending NSR case-by-case applications only. Permits by rule and standard permits are not listed here.
- TCEQ began publishing pending applications to its Permit Search Portal on August 31, 2026; this listing may thin out and the portal is the follow-up source.
- On September 21, 2026 the Governor directed TCEQ to pause issuing permits for data-center infrastructure. Pending filings are still listed; the pause can lengthen the gap before onsite generation is authorized. That is context for the call, not evidence about any one project.
- Summary PDFs are fetched newest-first, at most `max_summaries` per run. A failed or unparsable summary leaves the row as unsited evidence and does not fail the source.
