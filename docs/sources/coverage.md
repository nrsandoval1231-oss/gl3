> Historical coverage/requirement snapshot: the observations and remediation status below are dated October 20–22. For the accepted deployed application use the [November 2 receipt](../validation/production-release-20261102.md); for current target acceptance use [delivery status](../delivery/milestones.md). Deployment does not refresh these source-health counts or prove scheduled coverage.

> October 22 regional mandate supersedes the geographic policy in this dated snapshot. See the [complete regional inventory](regional-inventory-20261022.md) and [current engineering evidence](../operations/regional-stabilization-20261022.md). Earlier counts and runtime health below remain historical.

# Source coverage

Observed 2026-10-20. The authoritative source inventory and enabled state are in [`registry.v1.json`](../../config/sources/registry.v1.json); source-specific limits and evidence interpretation belong in the linked source notes. Collection breadth is not nationwide completeness.

The production registry had 26 entries. Recent successes were mixed: 19 entries had a recent success, while Boston, Chicago and Georgia last succeeded October 14. California CEQAnet, TCEQ NSR and Houston had no successful check. TDLR remained disabled in the registry. These dated observations are not a claim that every enabled source is healthy or current.

The PRD launch requirement remains open: 12 independent feeds across five source families, two national structured sources, and three industries, with seven measured daily cycles and reviewed opportunity evidence. Source count alone does not satisfy it. See [delivery status](../delivery/milestones.md) for release gates and [operations status](../operations/README.md) for the production observation and its limits.

On October 20, the owner authorized site-specific news to create standalone discovery Signals while leaving power facts unknown and Prospect/Lead gates unchanged. The repository implements versioned admission and bounded retained reassessment; see [news interpretation and its measured limits](project-interpretation.md). Frozen positive holdouts exposed misses and were subsequently used for development; prospective generalization remains unverified. This implementation is not deployed by this remediation. See the exact [owner decision](../decisions.md#owner-decision-october-20-2026-site-specific-news-may-create-discovery-signals).

## Authorities

- [Source onboarding](onboarding.md): acquisition requirements and access boundaries.
- [Source notes](.): source-specific behavior and limitations.
- [PRD](../product/PRD.md): product scope and evidence requirements.

Older source audits and local retrieval reports are dated evidence. They describe only their named candidate and observation period.

## October 30 acquisition candidate

The [bounded GovInfo notice capture](../validation/govinfo-complete-notice-20261030.md) retains complete newly captured target notices, preserving engineering text previously lost after 1,200 characters. It leaves existing source eligibility and immutable earlier evidence unchanged. The retained two-page historical PDF is a regression fixture, not proof of current engineering coverage or deployment.

## November 3 TCEQ application documents (workstream 1b)

The `texas-tceq-nsr-pending` entry carries an optional stage that checks the AC/TC application file (a PDF Portfolio) of each in-scope filing: HEAD at most once per second, download only when new or changed, composite PDF to the [permit extractor](../engineering/permit-document-extraction-20261103.md), PI-1 workbook to a read-only unit-type summary. It ships **disabled** (`application_documents.enabled` is `false`); enabling it is a registry change through the protected release ([activation notes](../strategy/ws0-production-env-changes-20261103.md#source-activation-registry-change-not-an-environment-variable)). Behavior, bounds, failure codes, the time budget and the measured tests are in the [engineering note](../engineering/tceq-application-documents-20261103.md).

Against the readiness gate above, only in the repository and on a mock origin plus a disposable database: retrieval and streaming, replay of identical input, a changed-bytes version that keeps earlier evidence, and typed visible failures (HTML shell, wrong type, oversize, unreadable, empty text, zero rows, rate limiting, time budget) that keep the previous accepted state. One dated live smoke (2026-11-03, four filings) exercised real portfolios once; it is not evidence of production retrieval. Not shown: production retrieval through the intended worker, sustained scheduled cycles, source breadth, useful observations inspected against the originals, or that TCEQ keeps serving the files as portfolios. Most filings describe on-site generation, which is stored as supply and never feeds demand. Cadence stays 24 hours like its neighbours; nothing here enables a paid provider.
