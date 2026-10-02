# GridLens UI/UX — canonical interactive environment

**Status:** LOCKED by Nick Sandoval on October 1, 2026.  
**Owner decision:** “This is the one! Make this the canonical UI-UX.”  
**Scope:** GridLens application in `gl3`. This is a design-authority update, not a claim that the production application has been rebuilt.  
**Product authority:** [PRD](../product/PRD.md). Its evidence rules, qualification gates, national scope, and commercial requirements remain authoritative.  
**Reference identity:** [Canonical reference manifest](references/canonical-ui-reference.json).

## 1. What is approved

The approved visual reference is the owner's attached **720 × 450 screenshot** of the original interactive study, headed **“A wider view. A sharper focus.”** Its companion behavior reference is **`gridlens-interactive-study.html`**. Use the exact assets identified by the manifest, not a similarly named regenerated mockup.

> GridLens is one continuously transforming intelligence environment. Start with the nation; select a signal; let the environment become the pursuit. Geography, project, power need, evidence, buying chain, and action retain their identity as the user moves through them.

The quiet, atmospheric, full-canvas composition is the design—not just a background behind a dashboard. Preserve its hierarchy, negative space, restrained geography, type, density, and motion language. Improve usability and production reliability without redesigning it.

**Superseded:** the September 24 light-canvas browse/detail layout, its always-visible tier-tab requirement, and later image-generated dashboards/storyboards with large sidebars, dense cards, neon maps, or permanent map/dossier split panes. `references/browse.webp` and `references/detail.webp` remain historical artifacts only, even where older documents still link them. The owner-provided brand system remains valid. Nucleus supplies the continuity principle, not GridLens's visual identity.

## 2. Frozen visual direction

| Element | Canonical requirement |
| --- | --- |
| Environment | One edge-to-edge deep-navy field with subtle atmospheric depth. No permanent boxed dashboard frame, hero mountain photograph, decorative particle field, or excessive bloom. |
| Identity | Approved GridLens Aperture and wordmark together, once, at top-left. Infrastructure Intelligence is the restrained supporting descriptor. Use approved assets from `web/public/brand`; do not redraw or replace the mark. |
| Palette | Deep Current `#101F2D`, GridLens Navy `#17324A`, Steel `#395A75`, Atmosphere `#6F879D`, Mist `#D5DEE5`, Ice `#F3F6F7`, White `#FFFFFF`. No Signal Blue `#3B82F6`, neon cyan, purple, or imported Nucleus colors. |
| Typography | Modern sans in the approved ABC Diatype direction; use an authorized font or existing fallback. Large, light-weight editorial headings; clear project names; quiet secondary labels. Do not copy the screenshot's scaled-down text sizes into production. |
| National composition | Left: short orientation, selected/featured pursuit, compact timing context, one useful action. Center/right: integrated U.S. map with fine state outlines and sparse, meaningful project markers. Alaska and Hawaii remain reachable. |
| Controls | Compact context/back control at upper-left beneath the header. Compact industry Lens and Signals / Prospects / Leads selector at upper-right. A restrained, discoverable secondary menu; no permanent wide navigation rail. |
| Selection | Restrained silver/ice marker and focus ring; surrounding content recedes. Marker prominence must have a stated purpose and cannot imply an unsupported load, confidence, or opportunity count. |
| Input | Anchored bottom command/search bar with visible current scope. Ordinary controls remain available; the user does not have to know commands or use AI to navigate. |
| Detail | Progressive disclosure within the same environment. Keep only information relevant to the current task prominent. A readable light writing surface may unfold for action, as in the original study. |

Brand geometry, clear-space rules, and asset licensing in [BRAND_ASSETS.md](BRAND_ASSETS.md) still apply. Never repeat the Aperture as a map pin, watermark, panel decoration, or replacement for a data object.

## 3. State and interaction contract

The original study demonstrates six modes: nationwide/home, project, power, evidence, buyers, and action. The previously requested state lens and richer tier/filter behavior are **production extensions to this same design**, not capabilities proven by the original study.

| State | What transforms | What remains anchored |
| --- | --- | --- |
| Nationwide | National geography and the selected pursuit provide orientation. Selecting a marker changes the subject; entering the pursuit enlarges that same subject and recedes the map. | Brand, Lens/tier controls, command bar, selected project identity. |
| State lens | Selecting a state smoothly reframes the same geography and reveals its matching records. No matching records produces an honest empty state, not invented markers. | Filters, tier, selected object where still applicable, national return context. |
| Project focus | The selected project title and power-need context move forward. Other projects recede; evidence, buyer, and action entry points emerge. Any facility illustration is labeled schematic unless source-backed. | Project and power-need IDs, return path, compact timing context, command scope. |
| Power need | The same compact timing object expands into a readable need-versus-suitable-supply view. Selecting a date or input opens the evidence for that claim. | Activity-specific facts and their IDs; unknown dates or supply remain unknown. |
| Evidence trail | Evidence unfolds around the selected claim, with source, date, excerpt/location, label, and contradictions. Opening a document does not lose the claim or pursuit. | Project, power need, selected claim, timeline context, previous viewport. |
| Buying chain | Relevant organizations and roles unfold as a relationship view; choosing a role reorganizes the view around it. Organization involvement, current employment, personal project assignment, and buying authority are separate claims. | Selected power need, source-backed relationship identities, next discovery question. |
| Action workspace | The relevant next question becomes an editable research/call brief or note. Other context recedes rather than disappearing. Missing contacts lead to discovery, not invented outreach. | Project context, tier, evidence, unsent draft and actual save status. |

**Back is restoration, not reset.** Restore prior state, geography, viewport/zoom/pan, Lens, tier, filters, sort, list position when applicable, selected project and need, selected claim/role, disclosure state, scroll, and keyboard focus. Preserve drafts separately from navigation snapshots. A refresh/deep link may restore only supported persisted state; do not promise session-only data survives restart.

**Filters change the environment.** Recompute visible markers, clusters, counts, featured pursuit, and empty states from the same result set. Preserve map position unless the user chooses to reframe. If the selected item stops matching, keep its context visibly marked “outside current filters” until the user returns or chooses another item; do not silently replace it. Changing a viewing Lens never silently narrows national ingestion.

**Actions are real and bounded.** Saving a note or status requires a persisted success result. A draft is not a sent message, a saved note is not a completed call, and a task status is not an evidence-tier promotion. Automated outreach is not introduced by this design decision.

## 4. Motion rules

Use the original study as the choreography reference: selected objects move, expand, recede, and return; unrelated screens do not simply crossfade behind a stationary dashboard. Preserve object identity with stable keys and a small shared scene-state model.

Implementation starting ranges—not separate visual approvals:

- Hover/focus and small control feedback: 120–200 ms.
- Disclosure/filter changes: 200–400 ms.
- Major focus transformations: approximately 700–1100 ms, with a settling atmosphere/map layer up to 1500 ms where useful.
- Primary easing follows the study: `cubic-bezier(.22, 1, .36, 1)`.

Do not make data or input wait for animation. Transitions must be interruptible, with no stale selection after rapid clicks or Back. Prefer transform/opacity animation; avoid continuous decorative loops. Respect reduced motion by retaining hierarchy and focus without camera movement. Keep controls usable during loading and failures.

## 5. Product truth survives the visual change

Tier belongs to an individual **power need**, not necessarily the entire campus. Different activities at one project may have different tiers. Tier, pursuit status, lifecycle, priority, and confidence remain separate.

| Tier | Required presentation |
| --- | --- |
| Signal | Dated source, identifiable site/project/company, specific reason to investigate, and next question. Unknown MW, supply, start, and duration are explicit. Do not draw a definite gap from absent utility information. |
| Prospect | Supported actual power requirement plus independent evidence that suitable supply may be late or insufficient. Show the missing facts blocking Lead qualification. |
| Lead | Supported remaining need, activity/location, MW range, start window, duration range, explained supply gap, likely buying organization/role, and next action. All material inputs trace to evidence. |

No confidence percentages, manual “Add to Leads” promotion, campus-MW substitution, generic company contacts presented as buyers, or fabricated service dates. Preserve Reported, User-confirmed, Inferred, Derived, and Unknown labels; material conflicts block unsupported conclusions.

Apply the PRD's inclusive 300 kW visible commercial floor with no maximum; unknown-size Signals stay visible and labeled. Prioritize direct users and responsible GC/EPC/electrical/commissioning contractors, not rental intermediaries. Preserve the distinction between data-center construction, commissioning, and bridge needs; upstream O&G production and fixed-infrastructure lifecycles remain distinct.

A national map is national **scope**, not proof of comprehensive live coverage. Source coverage, freshness, partial ingestion, failed/overdue checks, and unmapped or approximate locations must remain discoverable and honest. “Today” counts reflect actual material changes, not repeated retrievals. The study's fictional projects, dates, six-month mismatch, and sample counts must never seed production or substitute for acceptance evidence.

## 6. Minimal production components and state

Adapt the existing `web` application rather than starting a new app or importing another project's architecture. Keep the backend and accepted evidence intact.

Logical responsibilities: `EnvironmentShell`, `ContextBar`, `LensControls`, `NationwideMap`, `PursuitSubject`, `PowerWindow`, `EvidenceTrail`, `BuyingChain`, `ActionWorkspace`, `CommandBar`, and accessible loading/empty/error/source-health surfaces. These are responsibilities, not a requirement to create a file or service for every name.

Use one compact navigation reducer with a context-history stack, stable object IDs, current result set, selected claim/role, and map viewport. Keep fetched domain data and persisted drafts separate. The existing authenticated API remains authoritative for qualification and writes. Do not add a new orchestration framework, graph database, event bus, renderer, or map platform merely for this visual change.

Mobile preserves the same hierarchy in a readable vertical composition; the bottom input respects the keyboard and safe area. Provide keyboard access, visible focus, meaningful map/list alternatives, adequate contrast, and reduced motion. Unmapped opportunities must remain accessible outside the map.

## 7. Builder handoff and acceptance

1. Obtain and checksum-match the exact reference package in the manifest. Preserve the source originals; do not substitute the later image-generated dashboards. Read the original HTML as a behavior reference, not production data or a production architecture mandate.
2. Implement the shell and one real existing Signal through project → power/evidence → buying chain → action → Back, without replacing accepted backend behavior. Reuse current brand assets and authenticated APIs.
3. Extend the same scene with state focus and real tier/industry filters. Add empty, partial-coverage, unmapped, loading, conflict, save-failure, and reduced-motion states. Do not invent Prospects or Leads to fill the interface.
4. Compare the overview visually against the exact screenshot and demonstrate a short interaction recording. Check object continuity and return-context restoration, not just static colors. Run relevant repository checks and browser tests; report precisely what was and was not tested.

Acceptance requires desktop and mobile use; keyboard/reduced-motion use; rapid navigation without stale content; claim-specific provenance; independent tier/status behavior; correct filtered counts; real persisted action outcomes; and no fictional project data in normal operation.

**Non-negotiable builder instruction:** Build this approved experience. Do not reinterpret it as a generic dashboard, another design study, a permanent map/detail split, or a Nucleus-themed skin. Further visual redesign requires a new explicit owner decision. Accessibility, factual corrections, and production reliability improvements remain allowed within this direction.
