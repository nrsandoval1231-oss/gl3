# Approved Opportunity Intelligence Workspace

**Current candidate:** [results and viewport matrix](CANDIDATE.md), [visual discrepancy report](VISUAL_DISCREPANCIES.md), [desktop comparison](desktop-side-by-side.png), [overlay](desktop-overlay.png). The notes below retain the implementation boundary and earlier validation history; final controller results are in CANDIDATE.md.

This is the October 21 owner screenshot reproduction slice, on the existing React frontend and canonical authenticated APIs. Its backend dependency is PR102 (`feat/opportunity-intelligence`, base `5ef5f3f29e94fffb071351b61e186d236d40068c`). This UI branch does not duplicate or change that enrichment engine.

The exact [owner reference](../../design/references/opportunity-intelligence-approved.jpg), [brand sheet](../../design/references/brand-system-v1-owner.jpg), [provenance](../../design/references/opportunity-intelligence-reference.json) and [UI canon](../../design/UI_CANON.md) govern the result. Earlier silver/orange v3 presentation is historical.

## Implementation boundary

The workspace uses a dark branded header, real API opportunity sidebar, identity/completeness panel, five power metrics, project/customer rows, verified buying-chain contacts, separate commercial relevance/action panels, and a dense evidence workspace. Existing research, grouped Signals, Operations, source evidence, fact correction, call preparation, notes and status workflows remain canonical. No framework, schema, provider, budget, qualification or ingestion change is part of this UI diff.

Contact actions use the engine's current verified methods. Facility demand is not populated in this dependency, and no reliable utility energization date is projected. Supported utility service status may be shown with its status/basis while the date remains unestablished; missing fields render an explicit unestablished state. The qualified scoped gap retains its evidence semantics; campus capacity never becomes a temporary-power gap, and unknown supply never becomes zero. Completeness is separate from qualification.

## Acceptance dependencies

Licensed ABC Diatype Light, Regular, Medium and Bold files are absent. The supplied brand image establishes the typeface name but contains no installable fonts. Existing SVG wordmarks are documented approximations. Exact brand typography and official-master parity remain blocked; no screenshot is presented as font-complete acceptance.

PR102 retains its own backend implementation and retained-corpus/live-provider gates. Local UI fixtures cannot close those gates. No inference provider is activated to fill the screen. This branch authorizes no merge or deployment, and the parent Finish Contract remains open.

## Validation evidence

Controller raw logs, exact candidate manifests, full-size browser captures, side-by-side/overlay comparisons, measurements and independent review receipts are retained locally under `.artifacts/approved-ui` and `.agent/artifacts/APPROVED-UI`. Final delivery identifies the reviewed commit separately from any subsequent release state.

The first full frontend run is deliberately retained: 126 passed, 39 failed, one existing skip. Typecheck, build, dependency audit, documentation and diff checks passed. Integration repair addresses moved disclosures/menu controls, mobile selection/scroll and measured layout discrepancies without removing behavioral cases. Subsequent results must be read from the exact candidate delivery receipt; this historical failed attempt is not overwritten as a success.

The unchanged intelligence projection passed 19 targeted backend tests, including authenticated bounded reads, verified-contact provenance, no automatic facility-load gap and constant batch query scaling. The first test-environment attempt failed on non-UTF8 fixture encoding; a fresh UTF8 test database passed the same tests. No backend source repair was needed.

Current local browser validation uses a separate UTF8 database with 12 synthetic persisted project/need fixtures and 36 retained fixture evidence records. Four explicitly synthetic contacts exercise the current buying-chain projection on one record; other records exercise missing contacts. There is no worker and no provider execution. A failed older ingestion fixture runner crossed a Windows child-process boundary and performed source reads into another isolated database; it was stopped, preserved and excluded from every acceptance claim. An earlier retained-corpus runtime was offline. Its retained backup was subsequently found and restored, without modifying the source backup, into a separate isolated UTF8 database: 1,620 needs and 18,016 evidence records, with 1,619 active workspace records after rebuilding the derived browse projection. This is historical real-source snapshot proof, not live freshness or production acceptance.

Requested viewport matrix: 1648x928, 1440x900, 1280x800, 768x1024 and 390x844. Retain both exact-viewport and optional full-page narrow captures. Compare geometry against the owner image scaled to the primary viewport, and distinguish content/font differences from layout defects. Pixel difference alone is not a fidelity score when records and typography differ.

Performance samples describe local development-server selection/paint only, with synthetic persisted data and no render-triggered mutations. They are not production response-time claims. Final measurements and regression outcomes are bound to the final frozen frontend manifest and independent review.
