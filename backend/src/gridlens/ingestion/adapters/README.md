# Source adapters

Each adapter handles one publisher's access pattern and returns observations with stable source identity, dates, and retrieval metadata. Start with validated real sources; do not add dummy adapters to satisfy a count.

Boston uses official CKAN SQL queries over a rolling 90-day issue-date window, count-checked pagination and permit-number identity. A row reindex does not create new evidence; native status, applicant, amendment references and issue date remain distinct. Closed permits remain retained evidence. The published historical dataset total is not a current coverage or Lead count. Firecrawl is used for source discovery, not as an unbounded autonomous acquisition service; discovered routes are not enabled until a reproducible adapter is verified.
