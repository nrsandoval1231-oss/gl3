# TCEQ temporary concrete batch plant registrations

Source ID `texas-tceq-temporary-batch-plants`. Statewide Texas. Added October 14, 2026.

## What it is

The [pending-permit summaries page](https://www.tceq.texas.gov/permitting/air/newsourcereview/airpermits-pendingpermit-apps) lists every application in its public notice window: applicant, facility, registration number and a stable TCEQ project id. Temporary concrete batch plants registered for a named project are direct evidence that heavy construction is under way at that site. For each temporary plant, the Notice of Application and Preliminary Decision (`{registration}-napd-english.pdf`) gives the submission date, notice date, city, county and a map coordinate.

Checked October 14, 2026: 336 listed applications, 2 temporary batch plants:

- **DPR Data Center Temporary Batch Plant** (Amrize South Central, 173154L003): Midlothian, Ellis County; submitted May 14, 2026; notice May 28, 2026.
- **Project Apex Temporary Concrete Batch Plants** (Amrize South Central, 171358L004): Hubbard, Hill County; 300 yd³/hour. Nexus Data Center Hubbard's air permit (TCEQ NSR 183046) is also in Hubbard; whether these are the same project is unverified.

## Admission

A Signal requires a temporary plant whose facility names a data center or a named project, a dated notice, a site and the official link. Unnamed portable plants (road jobs, ready-mix relocations) stay evidence. The construction-power question is inferred; MW, duration, utility service date and buyer stay unknown. The batch plant operator is a materials supplier, not the owner or GC.

## Limits

- Registrations appear only during their notice window; past notices are not backfilled.
- The source declares `snapshot_complete`. When a registration leaves the page it gets a dated status-review flag; evidence stays.
- Notices are fetched at most `max_notices` per run. A failed notice keeps the prior stored version; more than half failing fails the check visibly.
