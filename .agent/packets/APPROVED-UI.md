# APPROVED-UI — screenshot reproduction

UTC start: 2026-10-21. Lane: full UI implementation; no architecture change.
Repository: nrsandoval1231-oss/gl3. Branch feat/approved-intelligence-ui-20261021.
Base: 5ef5f3f29e94fffb071351b61e186d236d40068c, dependency PR102 atop main 1c6c1cdc5f8d831c8106d4199a49e272b852f2eb.

Owner authority: October21 pixel-accurate UI directive in current conversation; supersedes conflicting prior UI/brand presentation rules. PRD governs evidence, qualification, authorization and workflows.

## Work graph
UI1 READY -> UI2 controller validation/browser comparison -> UI3 independent Sol review -> UI4 focused stacked PR.
One Luna builder, one dependency path. No opening Tribunal: existing project/architecture and fully pinned visual direction.

## UI1
Objective: faithfully reproduce supplied opportunity dashboard in existing frontend and preserve canonical interactions. Allowed: web/src/features/workspace/**, web/src/styles/workspace.css, web/src/styles/brand-tokens.css, web/tests/workspace.spec.ts, new focused web/tests/approved_workspace.spec.ts. No other ownership. Controller owns docs, state, test runtime, evidence and PR.
Exclusions: backend, schemas, providers, budgets, qualification, authentication logic, other feature internals, production, existing logo masters. No dependencies/framework additions.

Reference assets: C:/Users/nrsan/.codex/codex-remote-attachments/01a15e5e-c59b-7ac0-a67c-b2858d2aaadc/DD1CE459-5384-4AA0-8EF9-8EE4016C4C17/1-Photo-1.jpg (UI) and 2-Photo-2.jpg (brand). Read actual image. UI native 1280x720, requested primary 1648x928 (scale 1.2875). Header 45 native pixels (~58 primary), sidebar 320 native (25% primary), main padding14 native, metric strip89 native, three columns approximately 33/34/33%. Preserve composition. Brand tokens exact per owner. SignalBlue #3B82F6 accents authorized.

ABC Diatype is absent and requested from owner. Existing logo assets are permitted by owner; documented wordmark approximation is a known pending exact-brand dependency. Use existing aperture-gradient.svg + existing white lockup as appropriate, never redraw or invent marks. Declare ABC Diatype as preferred family without loading nonexistent/unlicensed files; report fallback as acceptance blocker. Do not claim parity.

Implement dark full-width header preserving real nav routes (no invented Platform/Solutions pages), compact light sidebar real API records with search/category filters/sort/paging, selected pale-blue row, main identity/actions, five metrics, three-column project/details + contacts + why/next action, bottom evidence table and tabs Evidence/Commercial Assessment/Research Gaps/Notes & Activity. Preserve access to existing Buying chain, Power gap, Timeline, Next steps, title/brief/fact/call/research workflows via disclosure or secondary navigation; don't delete them to simplify screenshot. Use aggregate intelligence_card from dependency PR102, no fabricated values. Missing metrics have concise truthful states and explanation. Only verified contact methods clickable. Share can copy canonical URL; pipeline action must use existing persisted workflow or visibly disabled reason. No new backend scope.

Maintain URL reload/back/forward, stale response guards, auth/loading/error/empty/stale states, data provenance. No per-list-row requests; read selected detail only. Tablet/mobile reflow with no horizontal page overflow. Real SVG icons, no emoji/Unicode substitutes. Do not hide defects via overflow:hidden.

Acceptance: screenshot geometry at five requested viewports; interactions and no providers invoked by render; meaningful automated tests including long names, contacts/missing contacts, source expansion, tabs, selection races, filters and history. Preserve existing behavior regressions where still meaningful; adapt selectors only for owner-authorized visual changes. Focused typecheck/build/tests then controller final suite. Two distinct repair attempts then re-plan. No push/merge/deploy by builder.

Handoff .agent/artifacts/APPROVED-UI/COMPLETION.json: changed files, validation commands/exit codes, UTC times/durations, repair count, model/config (UNKNOWN if unmeasured), unresolved dependencies and bounded claims. Builder does not grade own work. Controller independently reruns gates and Sol reviews exact frozen candidate.
