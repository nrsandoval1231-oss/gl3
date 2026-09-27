# Local public-news breadth evidence

**Observed:** September 26, 2026 UTC
**Execution boundary:** direct public feed retrieval and local collection design; no deployment or outbound alerts

The six publisher endpoints were directly checked by the controller and returned HTTP 200 XML. Inspected latest publisher snapshots contained:

| Publisher | Unique items | Oldest to newest publication date | Observed breadth |
|---|---:|---|---|
| Data Center Dynamics | 20 | September 24–25, 2026 | Applied Digital Alabama data-center coverage appeared in the sample. |
| Utility Dive | 10 | September 23–25, 2026 | Utility, grid, and energy sector news. |
| Manufacturing Dive | 10 | September 22–25, 2026 | Hanwha's Arkansas campus coverage and international manufacturing items appeared. |
| Construction Dive | 10 | September 23–25, 2026 | Contractor awards and a Lego Mexico expansion appeared. |
| Oil & Gas Journal | 25 | August 18–September 25, 2026 | Offshore final investment decisions and other international energy coverage appeared. |
| MJBizDaily | 30 | September 14–25, 2026 | Cannabis-sector licensing and facility-business coverage appeared. |

These samples describe what the publishers exposed at inspection time. They do not establish completeness, recall, or that every retained item describes a US project. DCD and OGJ are global feeds; the other feeds are US-focused and may include international coverage. An item about a contractor award, company, industry, or facility does not by itself identify a power need.

The implementation requests only the configured feed endpoint. It rejects redirects, HTML/login responses, malformed or unsafe XML, oversized feeds, unexpected empty feeds, unsupported continuation links, missing titles/dates/identities/links, off-host or unsafe links, future dates, and conflicting duplicate IDs. Canonical item links identify observations so a publisher GUID correction does not create a second item. Repeated identical content adds no evidence row; material retained changes create a new evidence version. Summaries are limited to 500 characters; full article pages and `content:encoded` are not fetched or retained.

Each successful worker retrieval reports snapshot item count and publication-date bounds in health. This is the latest rolling publisher snapshot, not a rolling historical query or backfill. Hourly polling can still miss news after downtime if the publisher rotates it out before the next poll, particularly when the local computer is off. The retained item displays collection state, source, scope, publication date, first-seen time, latest evidence time, excerpt, hash, and citation.

RSS now retains each Observation/Evidence version and runs the bounded project interpreter after the evidence commit. Its Signal and Prospect gates, offline review command, and limits are documented in [project interpretation](project-interpretation.md). MJBizDaily items stay in the general inbox; the cannabis business-news watch presents deterministic title/summary topic matches with their matched terms and “Topic match - review required.” A topic mention is not proof of a facility announcement, a project location, a power need, or a qualified opportunity. The watch has no outbound alert behavior and does not provide production or cultivation instructions.

Controller access/snapshot evidence is stored under ignored `.artifacts/breadth-probes/`. Those probes were not seeded into PostgreSQL. Persisted worker retrieval, identical replay, browser runtime behavior, and final combined acceptance are separate controller-owned checks and are not claimed by this document.

## Persisted local checkpoint

The controller ran the new worker against all eight configured sources on September 26. The six RSS feeds added 105 observations: DCD 20, Utility 10, Manufacturing 10, Construction 10, OGJ 25, MJBiz 30. Total storage is 197 observations and 198 evidence versions. The inbox exposes all 198 versions, including the existing government/NC evidence. Three cannabis topic matches are visible for review; these are not three cultivation projects or power opportunities. The three existing Signals and four retained project/need histories stayed unchanged.

All eight jobs succeeded on first attempt on the subsequent replay; all stored counts and the qualified Today digest were unchanged. Source health reports each latest snapshot boundary and its coverage limitation. Final acceptance, exact candidate and browser checks are recorded in [the local breadth validation receipt](../delivery/ingestion-breadth-validation.md). No cloud activity or launch-gate completion is claimed.
