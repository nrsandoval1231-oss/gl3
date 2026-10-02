# GridLens application UI — approved focus experience

**Owner decision:** Nick Sandoval, October 1, 2026.  
**Status:** Interaction target approved; production implementation NOT YET accepted.  
**Scope:** The existing private GridLens application in `gl3`. No new application or repository.  
**Product authority:** [PRD](../product/PRD.md). Its qualification gates, evidence rules, and October 1 commercial presentation amendment remain authoritative.

## Decision and precedence

GridLens is one continuously transforming commercial-intelligence workspace. Selecting a pursuit changes the surrounding environment, not merely the contents of a fixed dashboard panel.

**Nationwide → Project → Power need → Evidence → Buying chain → Action → exact return.**

This owner-approved decision supersedes the September 24 list-first layout, light-canvas requirement, and 200–300 ms page-transition prescription. Earlier browse/detail screenshots are historical references, not the new implementation target. Their evidence discipline and commercial requirements remain in force. The approved target is the interactive GridLens study, not the earlier static national dashboard mockup and not a recreation of Nucleus branding.

## Exact reference

The owner-approved attachment is `gridlens-interactive-study.html`, 157,948 bytes, SHA-256:

`6274e7012a1def344dbbe2c2acda89a7b8cf0a98e359e49f9e16e0bc3a486b2e`

The matching owner-supplied brand photo is `C5806D77-707A-459A-9624-96EDD2E51A92.jpeg`, SHA-256:

`db3b86914a18f238474352572b322af6b78b92b55ec34bf39f2c95be74d66aec`

The original HTML and brand photo are included in the accompanying `gridlens-production-handoff.zip` delivered in the approval conversation. This documentation change records their identity; it does NOT claim that their bytes are already checked into Git. Before visual implementation, import the unchanged HTML into `docs/design/references/gridlens-interactive-study.html`, verify its checksum, open it in a browser, and use it for side-by-side comparison. Do not invent a replacement when the attachment is unavailable; report that specific missing artifact.

The study contains fictional scenarios, schematic site geometry, scripted commands, and session-only drafts. It is an interaction reference, NOT a source of production data or proof of integration. Preserve the original separately from the production port. Confirm map/asset provenance before promoting reference assets into shipped application assets.

## Brand and visual identity

Keep the geometric GridLens Aperture and wordmark together, once, at the top left. Preserve the owner-supplied mark; do not replace it with a camera-shutter icon, cube, Nucleus symbol, or repeated background logo. Use the existing approved vector assets when they match the owner reference.

Use GridLens Navy `#17324A`, Deep Current `#101F2D`, Steel `#395A75`, Atmosphere `#6F879D`, Mist `#D5DEE5`, Ice `#F3F6F7`, and white. The approved environment is dark navy with restrained atmospheric depth and ice/white action surfaces. Do not import Nucleus colors or add electric signal blue as the dominant application accent.

Preserve the study's spacious composition, quiet typography, anchored input, and hierarchy. Use a licensed ABC Diatype asset only when available; otherwise use a readable modern system sans. Production body text must remain readable without scaling an entire desktop screen into tiny mobile text.

No generic card dashboard, permanent split-panel dossier, decorative rotating globe, particle field, fake satellite detail, or orbital solar system. Lists remain useful as an alternate representation and for records that cannot be mapped; they do not replace the approved environment.

## Required transformations

| State | Required behavior |
| --- | --- |
| Nationwide | Show the United States, with Alaska and Hawaii represented or reachable. Show actual accepted records and source coverage, not invented national completeness. Support the industry lens, tier controls, search, and an accessible list. Selecting a mapped signal changes the whole composition. |
| Project | Preserve the selected project's identity while the surrounding map recedes. The project, activity-specific need, known facts, unknowns, and next useful question become the focus. Do not show a schematic as an actual site model. |
| Power need | Expand the SAME timing/power object into an analytical view. Separate requirement, suitable supply, and remaining gap. Unknown dates or load must produce an honest unresolved view, not fictional endpoints, durations, or a calculated gap. |
| Evidence | Keep the selected claim anchored while its supporting and conflicting sources unfold. Show claim-specific links, source dates, evidence status, and assumptions. Close evidence back into the claim rather than navigating to an unrelated document dashboard. |
| Buying chain | Reorganize relationships around the selected organization or role. Distinguish project involvement, current company role, personal project assignment, and purchasing authority. Supported and inferred relationships are visually AND textually distinct. Unknown contacts stay unknown. |
| Action | Let the selected buying question become an editable discovery/call workspace. Keep the project and unresolved facts visible. Save a note or outcome through the real backend; copying/exporting a draft is not saving a call or sending outreach. |
| Back | Restore the prior arrangement, not only a URL. Preserve the selected project and need, tier, lens, search, sort, result context, map camera, evidence disclosure, selected role, scroll, and keyboard focus. Preserve unsaved drafts separately so navigation does not erase edits. |

The command/input remains anchored through these states. Initially it may support explicit commands, search, capture, and known contextual actions. Clearly distinguish those from any real language-model capability. Do not add a model dependency merely to navigate the interface.

## Motion and interaction

Use the original study as the motion reference: its principal layout transition is about 1,050 ms, with longer map transformations around 1,500 ms. Match the feel before tuning from measured performance. Do not substitute quick page fades and call that equivalent.

Maintain stable object identity while position, size, emphasis, and surrounding context change. Important examples are the project identity, timing window, evidence claim, selected buyer, and action question. Selecting a different role must visibly reorganize the relationships, not only replace text.

Transitions are interruptible. Rapid clicks, repeated back/forward, resize, and delayed API responses must settle on the latest intended state without overlapping controls or losing input. Inactive surfaces must not remain clickable or keyboard-focusable. Respect `prefers-reduced-motion`, preserve focus visibility, announce meaningful state changes, and offer keyboard-equivalent actions. Continuous decorative animation is not required.

## Production data rules — unchanged

- Signals, Prospects, and Leads remain evidence maturity, not visual importance, animation state, or a confidence percentage. Keep all three readily accessible. Priority, lifecycle, and pursuit status remain separate.
- A Signal requires sourced reasons to investigate. A Prospect requires an actual requirement AND supported supply insufficiency. A Lead requires the PRD's supported load, timing, duration, supply-gap, buyer-role, and next-action fields. Unknown utility status does not establish a gap.
- Every displayed value comes from accepted data with its proper label and source. Keep Reported, User-confirmed, Inferred, Derived, Unknown, conflicting, and stale distinctions visible where applicable. No sample names, illustrative dates, or fictional opportunities in live fallback states.
- Retain the inclusive 300 kW floor with no maximum. Retain unknown-size Signals with an unknown label. Campus total/nameplate/operating capacity is not temporary construction or commissioning load.
- Cover the country as product scope without claiming all states or sources are operational. Unlocated records remain accessible in a clearly labeled list. Do not silently discard records or place invented precise points. Geographic aggregation or approximation must be labeled. View filters must not stop national ingestion.
- Preserve project-bound owner/contractor role attribution. Prioritize direct users and responsible GCs, EPCs, electrical and commissioning contractors. Exclude re-renters as pursuit targets by default.
- Today/change counts must represent genuine new or material changes, not reprocessing or failed checks. Keep source health, last-success information, partial coverage, failures, and overdue runs accessible.
- Preserve authentication, existing ingestion review, pursuits, source inspection, evidence, and exports. Never expose private notes or source data through a public prototype or unauthenticated static endpoint. Writes use existing authorization; logout clears private client state.

## Build boundary and acceptance

Implement this in the existing React frontend and API. Preserve ingestion, identity resolution, qualification, evidence persistence, and existing databases. Start with a small local view-state reducer and the existing client; add dependencies only to solve a demonstrated need. No generic animation framework, new orchestration layer, separate demo application, or iframe presented as the product.

The first production slice must be a working authenticated **real Signal → focused project → exact return**, including honest unlocated/unknown/error states. Then carry the SAME pursuit through power, evidence, buying chain, and a persisted action. Do not stop after component scaffolding, this specification, or another mockup.

Acceptance requires the approved interaction feel AND verified real-data behavior: desktop and mobile browser evidence; ordinary and reduced motion; keyboard/focus and back/forward restoration; interrupted transitions and stale-response checks; honest empty/failure/unknown states; no auth bypass; and a note/outcome proven to survive refresh where saving is offered. A real Signal is sufficient to prove the flow; never manufacture a Lead to satisfy the demo.

Typecheck, build, appropriate browser/regression tests, and independent review must cover the exact candidate. Runtime/hosting acceptance is separate from code or design approval. Do not call the new interface shipped until Nick can open the actual authenticated application and complete that flow. Read [the execution handoff](BUILD_FOCUS_EXPERIENCE.md) before implementation.
