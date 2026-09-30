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

## GL3-017 merged: project buying chain

The slice adds bounded enrichment for a selected existing physical Project ID, with separate Project→Organization, Organization→Person/current role, and Person→Project relationships. DIRECT, ROLE_SUPPORTED and UNKNOWN remain distinct. The API retains project-specific source excerpts, semantic claim versions and run outcomes; the existing detail UI adds a compact inspectable Buying Chain section.

It starts from accepted evidence, reads exact Chicago contractor rows, and accepts up to four additional public links. There is no general web search, source-registry expansion, new worker/queue framework, outreach or tier promotion. Missing supported candidates are reported rather than fabricated to meet a count.

Three existing Chicago projects were manually reviewed against live official municipal/corporate sources: 3459792 (333 E Huron temporary electrical services), 3451848 (400 S LaSalle data-center conversion), and 3442494 (DMG Mori manufacturing renovation). Named construction/electrical-company leadership is ROLE_SUPPORTED; personal project assignment and buying authority remain UNKNOWN. Runtime/parser results and exact validation are recorded in docs/validation/gl3-017-buying-chain.md. Final captured-source parser/PostgreSQL acceptance passed all three chains (3/8/6 candidates), with unchanged replay at 17 claims, 9 evidence versions and 3 runs. Full checks: Ruff/mypy, 356 pytest passes and one existing missing local-probe skip, clean/repeat/drift migrations, frontend typecheck/build and zero npm vulnerabilities.

Saved-cloud validation on 2026-09-30 closes the browser execution blocker: all eight existing frontend tests pass (seven browser tests plus one pure grouping test), including real authenticated local browsing of reconstructed corpus records and synthetic buying-chain interaction/error cases. A reviewed one-line UI repair removes the misleading retained-findings sentence for empty results. Final backend checks again passed 356 tests with one existing local-probe skip, Ruff/mypy, PostgreSQL 18.4 clean/repeat/drift migrations, web typecheck/build and zero npm vulnerabilities. Generated API contracts are unchanged.

The live-retrieval acceptance gate still fails in the saved environment. Genuine production enrichment and replay for Chicago 3459792, 3451848 and 3442494 returned unresolved/zero candidates because all required public hosts fail DNS resolution (`gaierror [Errno -3]`), including outside the execution sandbox. Three failed-source run rows persist, with no buying-chain claims and unchanged power fields. No captured fixtures were substituted for live retrieval. Prior captured named chains remain ROLE_SUPPORTED only. See docs/validation/gl3-017-cloud-validation.json and the saved-cloud section in docs/validation/gl3-017-buying-chain.md for exact results and setup corrections.

GitHub inspection for GL3-018 on 2026-09-30 confirms PR #7 merged as `1f18a0182922fe8ee3fdc2225cf9c3f7c95d1fea`. Subsequent GL3-017 live acceptance was owner-reported; it is not fresh proof from this agent. The earlier saved-cloud failure record above remains historical evidence, not the current merge status. No deployment is claimed.

## GL3-018 merged

Fresh `feat/gl3-018` starts at current GitHub main `1f18a01`. Authoritative
admission separates eligible permits, project-specific official utility filings
and explicit temporary-power solicitations from supplemental news and unresolved
planning/entitlement context. Evidence/history remain retained; inactive historical
needs are not silently deleted. Source-specific acquisition remains in adapters,
policy in domain, persistence/application in ingestion, presentation in web.

The existing Georgia route now reports its actual Title V/SIP/synthetic-minor
scope and extracts bounded page-cited generator facts from narratives/drafts.
Current application links are empty: full air-application acquisition remains
unproven. Chicago includes official Express Electrical Work, retaining parcel,
case, scope and contractor roles. Registry remains 13 sources; there is no new
state, utility docket, procurement or RRC connector. Generator nameplate is not
rental demand, and unknown energization does not prove an unmet supply gap.

First ordinary-worker live runs succeeded for Georgia (19 observations/38 PDFs,
9 Signals/10 rejected), Chicago (1,528 rows, 16 Signals/1,512 rejected), and DCD
(20 retained news items, no independent needs). Exact replay preserved counts.
Final corrected extraction retains 1,719 evidence versions and 43 change events;
all 25 exposed needs have Official permit provenance, unknown required MW and unknown
suitable supply. Chicago recovered from an intermediate HTTP failure; final acquisition
and replay succeeded for all three sources. Full validation: Ruff (including migrations),
mypy, 381 pytest passes/one existing local-probe skip, clean/repeat/drift migrations,
frontend typecheck/build, zero npm vulnerabilities and all nine Playwright tests.
Final candidate checks and review are recorded in
`docs/validation/gl3-018-validation.md`. PR #8 is merged on remote main `7f241748f421697877b54ba3f87eb5b0b3e839e1`, freshly fetched for GL3-019. No deployment is claimed.

## Later scope

National coverage, deployed daily operation, full air applications, direct rental
and load-bank procurement, broader electrical/commissioning and utility milestone
acquisition remain unproven. Planning/entitlement standalone Signal admission
still needs an owner decision. The existing Prospect/Lead evidence gates remain
authoritative; this slice does not promote on score or equipment MW.

## GL3-019 in progress

Fresh branch from verified remote main `7f24174`. Priority: data-center construction temporary power, commissioning temporary power, then O&G temporary power. All drilling permits are eligible early production Signals; they do not prove production date, MW, fuel suitability, rental demand or a supply gap. Preserve asset-specific lifecycle and separate relationship evidence. Repair retained permit enrichment before broadening source count. Exact scope and validation are recorded in `docs/sources/gl3-019-permit-enrichment.md`.
