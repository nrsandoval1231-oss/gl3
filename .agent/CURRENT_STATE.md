# Current state

GridLens is focused on turning evidence-backed Signals into commercially useful pursuits without inventing unsupported power facts.

## Implemented through GL3-016

- The ingestion foundation retains source observations, evidence versions, lifecycle history, source health, and project-oriented Signal cards across 13 enabled public sources.
- GL3-015 established the lifecycle-based Signal Source Matrix, acquisition gap audit, Taylor planning lifecycle proof, and retained conflicting/withdrawn evidence.
- GL3-016 is merged on main. It adds one bounded TypeSafe Jev adjudication path for ambiguous retained Signal evidence, a conservative GridLens SHOW / REVIEW / HOLD policy, persisted reproducible decisions, and conservative physical-project grouping.
- Jev does not replace deterministic facts or evidence. It adjudicates bounded ambiguity; underlying observations and evidence remain authoritative and inspectable.
- The accepted frozen GL3-015 corpus contained 81 Signal records displayed as 63 cards. GL3-016 local validation reported 264 backend tests passing with one skip, web typecheck/build passing, zero high-severity npm audit findings, clean migration checks, and live Jev validation. Hosted CI remained blocked before runner execution by the GitHub account billing/spending-limit condition.

## Current limitations

National acquisition coverage and deployed daily operation remain unproven. Current RRC ingestion, broad utility/large-load records, and many construction/commissioning lifecycle sources remain absent or partial. A Signal is still not a Prospect or Lead unless evidence supports the actual power requirement, supply gap, timing, and commercial path.

## GL3-017 draft: project buying chain

The slice adds bounded enrichment for a selected existing physical Project ID, with separate Project→Organization, Organization→Person/current role, and Person→Project relationships. DIRECT, ROLE_SUPPORTED and UNKNOWN remain distinct. The API retains project-specific source excerpts, semantic claim versions and run outcomes; the existing detail UI adds a compact inspectable Buying Chain section.

It starts from accepted evidence, reads exact Chicago contractor rows, and accepts up to four additional public links. There is no general web search, source-registry expansion, new worker/queue framework, outreach or tier promotion. Missing supported candidates are reported rather than fabricated to meet a count.

Three existing Chicago projects were manually reviewed against live official municipal/corporate sources: 3459792 (333 E Huron temporary electrical services), 3451848 (400 S LaSalle data-center conversion), and 3442494 (DMG Mori manufacturing renovation). Named construction/electrical-company leadership is ROLE_SUPPORTED; personal project assignment and buying authority remain UNKNOWN. Runtime/parser results and exact validation are recorded in docs/validation/gl3-017-buying-chain.md. Final captured-source parser/PostgreSQL acceptance passed all three chains (3/8/6 candidates), with unchanged replay at 17 claims, 9 evidence versions and 3 runs. Full checks: Ruff/mypy, 356 pytest passes and one existing missing local-probe skip, clean/repeat/drift migrations, frontend typecheck/build and zero npm vulnerabilities.

Two acceptance limits remain explicit: the direct application reader cannot resolve public DNS in this cloud execution, and browser interaction/visual tests cannot run under the current browser/runtime restrictions. Captured real-source parsing and PostgreSQL persistence are partial proof, not a passing direct live-discovery or browser check. Keep the PR draft; do not merge or deploy.

## Later scope

GL3-018 remains later acquisition expansion for construction, electrical, temporary service, commissioning, energization, planning, utility, RRC, and fixed O&G lifecycle evidence. National coverage and deployed daily operation are still unproven.
