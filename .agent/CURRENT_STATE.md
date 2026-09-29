# Current state

GridLens is focused on Signals. The existing GL3 ingestion foundation retains source observations, evidence versions, conservative project matching, lifecycle history, source health, and project-oriented Signal cards. The product scope for GL3-015 is acquisition and Signal quality; Prospect, Lead, contact research, and outreach automation are outside this slice.

## Implemented in GL3-015

- `docs/sources/SIGNAL_SOURCE_MATRIX.md` defines the lifecycle-based acquisition universe and inference boundaries. `docs/sources/SIGNAL_GAP_AUDIT.md` records actual coverage and acquisition gaps.
- Taylor, Texas Development News/Notices is one ACTIVE local municipal planning source. The planning family remains PARTIAL. The adapter retains article and archive revisions with attributed evidence, bounded retrieval, source health, and idempotent replay.
- A later official Project Mustang withdrawal remains linked to the earlier planning notice. The Signal card identifies the earlier notice as historical, the planning application as withdrawn, and overall project viability as UNKNOWN. Conflicting same-ID or archive revisions remain evidence without falsely withdrawing a project.
- Chicago permit retrieval selects mapped fields to stay within its response-size bound. No RRC source is active; historical W-1 parsing had offline proof, while current-file retrieval and compatibility remain unverified.

## Verified locally

The fresh isolated cleanup run migrated from empty to head, ingested all 13 enabled sources, and replayed without duplicate content: 2,802 observations, 2,839 evidence versions, 81 Signal records, and 63 displayed project cards. Taylor retained 25 observations, two Signals, and three material changes. The authenticated card shows Mustang withdrawn with both evidence versions. The unsanitized [Signal review](../docs/validation/gl3-015-persisted-signal-review.md) records 11 SHOW, 29 REVIEW, and 23 HOLD. Ruff, mypy, 240 backend tests with one skip, web typecheck/build, and npm high-level audit passed locally.

## Unknown and next problem

Taylor does not imply Texas-wide or national planning coverage. Deployed daily cadence, current RRC ingestion, broad utility/large-load records, and many construction lifecycle sources remain unproven or absent. Signal precision and conservative project consolidation are the next product problem; weak event, maintenance, stale, and same-site cards remain visible in the review. GL3-016 is the next milestone and has not started.
