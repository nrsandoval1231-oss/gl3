# Contact intelligence release and backfill procedure

This is a reviewable procedure. No production backfill, merge or deployment is
authorized by it. The owner requested an isolated benchmark and production
preparation; production changes require separate explicit authorization.

## Established production identity and baseline

The read-only October25 inventory observed all application services on
`release-6394de644591`, database `gridlens_restore_20261014`, migration
`0041_evidence_packages`. See the [point-in-time inventory](production-inventory-20261025.json).
Recheck every image ID, schema, current source versions and deployment flags before
release; the database name is the live target even though it contains "restore".

The benchmark clone is a new loopback PostgreSQL18.6 instance, separate from the
application and test databases. The original full dump and hashes, restore receipt,
original-row fingerprints, per-company checkpoints and public retrieval evidence
are retained locally outside Git. Do not upload credentials, raw backups or private
notes to the PR. A successful archive listing is not restore proof.

## Preflight before an authorized production change

1. Pin the reviewed candidate commit and verify backend/frontend match. Confirm
   deployed image IDs and actual Alembic revision, not only image labels.
2. Run migrations twice and drift checks on a newly restored staging database;
   this contact increment must not require destructive data changes. Run old-image
   compatibility/readback before treating rollback as rehearsed.
3. Fingerprint the pre-existing company/project/need/membership/correction rows and
   contact claim/evidence history. Verify the same original rows after staging
   enrichment. New contact claims may append; qualification and original evidence
   must survive. In particular preserve the63existing contractor contact claims.
4. Check queue concurrency, source/public acquisition limits, per-company URLs,
   deadlines, maximum attempts and refresh policy. Start with one contact worker
   lane and a small batch. A provider failure must not stall ordinary ingestion.
5. Inspect every provider's key/configuration without printing it. Native-only
   execution and configured Firecrawl search are separate proofs. No key, credit,
   unit price or authorization means paid discovery stays disabled. Do not enable
   a commercial people-data provider, auto-recharge or new subscription.
6. Obtain and checksum an authorized recovery checkpoint. Verify off-host retention
   and restore readiness separately. Preserve all pre-existing databases/backups.

## Prioritized and resumable execution

Use `scripts/company_contact_enrichment.py` to inventory and prepare the existing
eligible canonical companies. Priority is Lead, high-value Prospect, remaining
Prospect, Signal. The current production snapshot has no Lead or Prospect company;
those tier coverage percentages are N/A. Do not promote Signals to fill the sample.

Commit the reviewed plan's identity/digest before running. URL inputs are discovery
hints only; never insert contact values into a manifest. Run bounded pages and save
each company/job checkpoint. Re-run the same manifest and checkpoint after an
interruption; inspect running, failed and uncertain jobs before any retry. Enqueue
success alone does not establish successful discovery or contact coverage.

The current operator tool restricts apply/run to an explicitly named loopback
database. Use it on an isolated snapshot. A future production execution mechanism
must be separately authorized and retain exact-target guards; do not remove the
loopback check as an operational workaround.

After each batch inspect terminal outcome/reason, actual verified method count,
named professional roles, direct versus generic methods, source URLs/dates and
remaining research. Inspect company API and selected-company panel after reload.
Confirm company-ID and contact-method deduplication across related projects and
that a refresh never erases a still-supported contact or operator correction.

## Cost and rollback

Native public HTTP does not consume a paid enrichment provider. Attribute cost0
only when instrumentation confirms no paid calls; unmeasured provider cost stays
UNKNOWN. The owner approved up to160existing-plan Firecrawl credits for isolated
validation. The first no-hint20company trial completed20searches and consumed
40observed credits (2614to2574); actual cash billing remains UNKNOWN. Its1/20usable
coverage is retained in [the v9 report](firecrawl-v9-results.json). A matched
policyv10 rerun is limited to40additional credits, cumulative80/160. The bounded
sample is not a coverage or cost forecast for all235companies. This isolated-use
approval does not authorize production enrichment, recharge or a new subscription.

For a future authorized production first pass, the current implementation makes at most one
Firecrawl URL search per company, requesting four web results, followed by native
retrieval. Firecrawl's [published search tariff](https://docs.firecrawl.dev/features/search#cost-implications)
is two credits for one to ten results, rounded up. Under that tariff and assuming
every company needs one search, twenty companies require at most forty search
credits and 235 companies require at most 470 search credits for one pass. These
are estimates, not production usage or approval. Paid scrape/map/JSON/PDF
features and retries are not included; they are not enabled in this pipeline.
The isolated trial reserves $0.01/search against finite logical-call dollar and
call caps. This is a conservative replacement reservation using the published
[$5/1000extra-credit price](https://www.firecrawl.dev/pricing), not a claim about
the account's cash bill. Reconfirm the actual account price, remaining credits,
caps and production authorization before dispatching in production; never
silently substitute unlimited spend. No additional paid provider was activated.

Pause the contact planner and let fenced in-flight work reach an inspected state.
An interrupted paid request is UNKNOWN until its logical call is reconciled; never
retry it blindly. Restore the prior reviewed application image/flags using the
owner-approved release procedure. Retain appended contact/evidence history; do not
delete companies, contacts or the entire database to roll back a UI or worker.
Use a full database restore only after separate authorization and exact recovery
target verification. Production rollback remains a plan until it is rehearsed.

Release recommendation remains HOLD until the final benchmark, exact-candidate
tests, independent review and requested runtime/provider gates are satisfied.
