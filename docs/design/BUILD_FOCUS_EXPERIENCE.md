# Implement the approved GridLens focus experience

You are implementing an approved product experience, not designing an alternative.

## Objective

Implement the approved experience in [UI_CANON.md](UI_CANON.md), preserving GridLens branding and connecting it to real application data. The [canonical reference manifest](references/canonical-ui-reference.json) identifies the exact owner-provided assets: use the overview image as the visual authority and `gridlens-interactive-study.html` as a behavior reference only. The HTML contains fictional data and does not define a competing visual target.

Done means Nick opens the authenticated GridLens app, finds a real Signal, focuses into its project, explores its actual power/evidence/buying context, records a useful outcome, refreshes successfully, and returns to the prior arrangement. The environment must transform around his intent as in the reference. A conventional dashboard with the same colors is not acceptance.

## Start here

Work only in `nrsandoval1231-oss/gl3`, not legacy GridLens repositories. Fetch current refs and inspect the working tree before changing it. Preserve all uncommitted work. Use one feature branch or isolated worktree; do not reset, force-push, or delete unrelated work.

The handoff was prepared against `main` commit `ce6b8fc688085c7a43f1bdefa35eeabeddb72903`. This is an inspection baseline, not a command to reset an advanced main. The October 1 locked `docs/design/UI_CANON.md` and its reference manifest govern visual and behavior references; this handoff supplies implementation sequencing and acceptance detail. Reconcile newer work without losing it.

Read `AGENTS.md`, `docs/product/PRD.md`, and the amended `docs/design/UI_CANON.md`. The October 1 owner decision replaces the old static/list-first visual target, not product/data requirements.

Find the attached `gridlens-production-handoff.zip` in the current task or Nick's Downloads. Extract it to a temporary directory, not over the repository. It contains the unchanged prototype and owner brand photo. Do not overwrite current repository files by blindly extracting the archive.

Verify the prototype SHA-256:

`6274e7012a1def344dbbe2c2acda89a7b8cf0a98e359e49f9e16e0bc3a486b2e`

Copy that exact file to `docs/design/references/gridlens-interactive-study.html`, retaining the original separately from production code. Open it in a real browser and click every state; do not infer the motion from screenshots. If the exact artifact is missing, report the precise blocker instead of replacing it with a new design. Verify asset provenance before reusing the reference's map geometry in shipped assets; where provenance is unresolved, use an attributable map asset with the same approved composition and motion.

## Reuse the actual application

The inspected frontend already contains:

- `web/src/app/App.tsx`: authentication, opportunity loading, selection, tier/search routing, browser history, source/ingestion views, and detail rendering.
- `web/src/api/client.ts` and `generated.ts`: the existing typed API contract.
- `web/src/features/opportunities/projectCards.ts`: project-oriented presentation/grouping and signal decisions.
- `web/src/features/buyingChain/BuyingChain.tsx`: project-bound organization/person enrichment presentation.
- `web/src/features/pursuits/Pursuits.tsx`: pursuits and owner call outcomes.
- `web/src/styles/` and `web/public/`: current presentation and brand assets.

Re-read those paths at the actual candidate before editing. Reuse and refactor; do not create a second app, duplicate database, or fresh backend.

The current client exposes `session`, `login`, `logout`, `opportunities`, `changes`, `health`, `ingestion`, `brief`, `requestBrief`, `buyingChain`, `enrichBuyingChain`, `pursuits`, and `savePursuitNote`. Use their actual schemas and identifiers. In particular, project ID, power-need ID, and pursuit ID are different; never pass one in place of another. Check whether a shown action has a valid existing persistence path. Add only the smallest necessary backend change where a genuine gap prevents the accepted flow; test it and regenerate the contract when required.

## Execute in this order

### 1. One real working vertical slice

Implement the authenticated nationwide/list representation → selected real Signal → focused project → restored overview path first. Reproduce the approved dark environment, Aperture lockup, persistent project identity, receding map, anchored command/input, and interrupted/back transitions.

Wire the existing opportunities and health data immediately. Do not spend the first slice polishing fictional records. No coordinates means a usable unlocated list, not disappearing records or invented map pins. Keep the current ingestion, source health, pursuits, logout, and other working routes reachable throughout the migration. A temporary internal toggle is acceptable only to keep the migration safe; remove the obsolete default once the replacement passes acceptance.

### 2. The same pursuit, deeper

Carry the same project AND power-need identity through Power need → Evidence → Buying chain → Action. Keep the timing object stable as it expands and contracts. Preserve the selected claim as sources unfold. Reposition the buying relationships around the selected role. Turn the unresolved buying question into an editable call/discovery workspace, not an unrelated modal.

Use actual supported facts, unknowns, source links, existing briefs, and buying-chain records. A fully useful unknown state is part of the design. Keep draft edits through navigation. Save notes/outcomes through the backend where offered; verify the saved result after refresh. Never simulate an email, completed call, contact discovery, or tier promotion.

### 3. Visual fidelity and completion

Compare each state and the transitions side-by-side with the original HTML at desktop and mobile widths. Preserve the spacious composition and the sense of the environment reorganizing; do not replace it with six static pages or permanent cards. Use the existing stack. Prefer straightforward React state, CSS/SVG, and stable component identity; do not introduce a generic scene engine or state-management framework without evidence it is necessary.

Use a small explicit state model covering mode, selected project and need, industry lens, tier, query/sort, map position/zoom, selected source/role, and return context. Keep drafts and server records distinct from navigation snapshots. Support browser back/forward and in-app Back consistently; reload must restore valid context or explain unavailable/deleted records. Cancel or disregard stale data requests; prior project responses must never overwrite a newer selection.

Finish with the real frontend default, not a hidden demo route, and update only documentation changed by the implementation. Do not add speculative architecture files.

## Non-negotiable tests and proof

Test actual rendered behavior, not only reducer snapshots:

1. Authentication and session expiry; no private data or notes available without authorization; logout clears private UI state.
2. A real retained Signal through project → power → evidence → buyer → action → return, without invented facts. A Signal is enough; missing Lead evidence is not a reason to fabricate data.
3. Tier and lens filtering, unknown-size eligibility, geographic unknowns, empty tiers, source failures, and accurate partial-coverage labels.
4. Correct project/need/pursuit identifiers and no cross-project data leakage after rapid selection or delayed requests.
5. The timing/claim objects stay continuous through transitions; buyer selection visibly reorganizes relationships.
6. Back/forward restores filters, result context, map camera, evidence/role selection, scroll, and focus; edited drafts survive.
7. Keyboard navigation, inactive-surface focus exclusion, reduced motion, rapid/repeated clicks, resize, narrow mobile screens, and long real project names.
8. Notes or outcomes survive reload and a new authenticated read. Copy/export is explicitly distinct from server save or outbound send.

Run the relevant repository checks, including:

```text
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web test
```

Inspect the repository test configuration first. Use real services where a check requires them; do not relabel API-intercepted fixtures as live-data proof. Run backend regressions when touched. Do not weaken tests or branch protections to obtain a pass. An account/runner failure is not a failed code test and not a successful run; record it honestly and provide locally rerun evidence when authorized.

Capture a short recording of the REAL application completing the flow, plus desktop/mobile screenshots and commands/results bound to the exact candidate SHA. Compare visual/motion fidelity separately from data/integration correctness. Request independent review; fix defects, rerun affected checks, and report merge/deployment status separately. Do not self-approve. Do not claim deployment from a merged PR or a listening local server.

## Keep going, without scope creep

Proceed through these bounded slices in the current build session. Do not stop after a plan, the first screenshot, a placeholder component, or a passing build with fake data. After two materially different failed repairs, reassess the failure rather than repeating the same patch. Stop only for an actual missing input, permission, unsafe conflict, or unresolved correctness issue; preserve the exact restart point and name the smallest required owner action. Do not ask Nick to choose a new design.

Final report: exact branch/SHA/PR; what works against real data; tests actually run; recording location; what remains unverified; and the exact existing-app startup/open instructions. Make no unsupported completion percentage or background-work promise.
