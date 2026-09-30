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

Taylor does not imply Texas-wide or national planning coverage. Deployed daily cadence, current RRC ingestion, broad utility/large-load records, and many construction lifecycle sources remain unproven or absent. GL3-016 remains a draft PR. A local live Jev run on the frozen 81-record review corpus produced 11 SHOW, 42 REVIEW, and 10 HOLD cards; all 13 differences from human review were HOLD to REVIEW. The [live adjudication review](../docs/validation/gl3-016-live-adjudication.md) retains every difference. A separate migrated clone of the persisted database replayed Jev decisions without adding duplicate rows and presented 11 SHOW cards out of 63; its newer Georgia evidence versions make it a distinct current-data check. Hosted CI remains blocked before runner start by GitHub account billing.

GL3-017 is the next intended slice after accepted Signal adjudication: project-specific buying-chain enrichment. It must connect a person to an organization, a specific physical project, and a relevant buying or influence role with evidence. GL3-018 is later acquisition expansion for construction, electrical, temporary service, commissioning, energization, planning, utility, RRC, and fixed O&G lifecycle evidence. Neither slice is implemented here.
