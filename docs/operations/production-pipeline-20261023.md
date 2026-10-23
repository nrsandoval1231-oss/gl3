# Production intelligence implementation record — October 23, 2026

The [owner directive](../../.agent/PRODUCTION_INTELLIGENCE_DIRECTIVE.md) defines
six sequential milestones. This branch begins with Milestone 1: PUCT docket
retrieval, normal saved-browse startup, and the approved desktop detail layout.
The full live Firecrawl → Jev → OpenAI → verified commercial record acceptance
remains open. This record does not authorize a production deployment.

## Milestone 1 implementation

- PUCT docket searches now use the official direct `/search/dockets/` endpoint
  with `ItemMatch=Equal`. The obsolete endpoint redirects. Exact-host/public-IP
  validation, rejection of redirects, bounded queries, and agreement between
  HTML and spreadsheet rows remain enforced. Docket evidence does not by itself
  establish a commercial opportunity.
- Local and production Compose start the existing provider-disabled browse
  maintainer after migrations. The API saved-browse feature flag retains its
  default. When enabled, the maintainer publishes the first generation without
  a manual rebuild; the API retains its pending response until publication.
  See [local startup](local-runtime.md) and [saved browse](saved-browse-b1.md).
- At 1280×800, the five metric cards retain the approved layout and complete
  values. Long evidence identifiers wrap within their cards; compact desktop
  values use 15px text. A cited synthetic fixture exercises long values,
  1648px geometry, and 390×844 horizontal bounds. These screenshots are layout
  evidence, not real-project acceptance.

## Local runtime evidence

The isolated loopback PostgreSQL cluster uses port 55443. Existing checkouts,
databases, and the separately running application are preserved. No paid model
or Firecrawl generation request was made for this repair milestone.

Fresh migrated startup was observed with real authentication: login 200,
unauthenticated Opportunities 401, enabled saved browse initially 503, then
Opportunities 200 with an empty list after ordinary `python -m
gridlens.jobs.browse maintain`. No manual rebuild was invoked. One intermediate
503 came from an API process holding a pre-edit policy fingerprint; restarting
that process at the matching revision resolved it without weakening the fence.

The first public PUCT adapter check returned ten unique dockets across the two
bounded queries. In the fresh UTF-8 database, the ordinary worker persisted ten
observations and ten evidence records in 2.606 seconds. Replay succeeded in
2.402 seconds with zero new records and ten unchanged records; semantic content
digests were stable. Both jobs are terminal successes. Actual HTTP request
count was not instrumented in the worker child process and remains UNKNOWN;
the adapter bounds each pass to four logical requests before transport retries.
These docket-index records remain evidence-only. Raw local receipts and layout images remain outside
Git under `.artifacts/production-pipeline/` and
`.agent/artifacts/PRODUCTION-M1-UI/`.

The validation harness encountered two local setup failures: a missing Windows
multiprocessing main guard, then a database created with Windows' default
WIN1252 encoding. The latter job committed ten evidence records before JSON
decoding failed in the receipt collector. The databases and failed receipts
were preserved. Empty receipt arrays cannot prove that a job had no effects;
durable job and content state must be inspected before retrying. Revised
verification databases use explicit UTF-8 encoding. No application evidence
was deleted to obtain a passing result.

## Verification and remaining work

Controller gates bind to the frozen Git candidate: Ruff/format/mypy, fresh and
repeat migrations with drift check, complete backend tests, dependency audits,
TypeScript/build, browser regressions including real authentication, and
documentation/diff checks. Independent review is required before accepting the
milestone. Exact command results and review identity are retained in the
candidate's ignored evidence directory and PR, rather than asserted in advance.

Milestones 2–6 remain open: five-source native/Firecrawl comparison, live Jev
evidence processing, actual configured OpenAI reasoning model, customer/project
and buying-chain resolution, classification investigation, regional source
coverage, and five-project live acceptance with measured costs and recovery.
Read-only provider metadata confirmed Firecrawl account access and Jev model
aliases; it does not prove either integration operational. OpenAI key setup is
pending. Credentials must stay in the secure local destination, never in Git
or validation output. No merge or production deployment has occurred.
