# Customer intelligence UI follow-up — November 13, 2026

This is a technical source-backed acceptance aid for the current account-first workspace. It does not claim salesperson/customer acceptance, deployment, or completion of the 20-customer commercial evaluation.

## PR #189 selective preservation checklist

Source comparison: PR #189 branch `origin/feat/premium-gridlens-ui` at `cfedab6c7a7e0531b430ab06f1ebe4acb3a53164`, its build-identity guard repair at `8fbf50b36644d20425718098067e7da0a6ecbda2`, and the account-first integration baseline `8112fb940c3575b375bdcc0bf471e81bfb0c8830`. The governing product sources are [Account-first foundation](../../../engineering/account-first-slice-20261107.md), [Autonomous Intelligence Canon](../../../product/AUTONOMOUS_INTELLIGENCE_CANON.md), and [UI canon](../../../design/UI_CANON.md).

| PR #189 contribution | Current source and decision |
| --- | --- |
| Full brand mark, four destination navigation, search and account menu | Preserved in `web/src/components/CanonicalHeader.tsx` and `web/src/features/workspace/Workspace.tsx`. Current masthead retains the approved GridLens mark and the four authorized destinations. |
| Research progress, Signals, diagnostics, build identity and sign out | Preserved in the current account menu in `Workspace.tsx`; `buildIdentity` is rendered there. |
| Account-first customer browsing, distinct project/need detail, source claims, contacts and pursuit actions | Current implementation and tests remain on the account-first branch. PR #189’s alternate card implementation was not copied wholesale. |
| PR #189’s architecture image/hero statement and larger redesigned masthead | Intentionally omitted. Current account-first direction retains the compact branded header and forbids decorative architecture/hero treatment. |
| “Shortlist / New today / In research” premium overview tiles | Intentionally omitted. Current canon removes mandatory KPI tiles and prohibits unavailable placeholder metrics. Current browse keeps its supported account count and filter semantics. |
| Account menu’s Profile dialog | Not carried into current UI. PR #189’s dialog accurately disclosed that authentication is a shared password session and no individual profile exists; it did not fabricate a profile. The existing menu remains account/session-oriented and no individualized profile workflow is authorized. |
| Local Settings / reduce-motion preference toggle | No new settings chrome. The system `prefers-reduced-motion` behavior remains for Companies, Reports, Pursuits and flat opportunity results; this follow-up also disables the customer account chevron transition under the OS preference, covered by a browser regression. |
| PR #189’s mobile header/search/detail styling | No separate visual redesign was retained. The current compact account-first layout is responsive; native UI evidence includes a 390 px phone capture. |
| Build revision, environment and build-time metadata | Preserved and hardened: production Docker builds require an explicit environment and 40-character SHA, reject a known dirty or mismatched Git checkout, then verify that the exact SHA string is in the compiled JavaScript. Production Compose passes an optional SHA so backend-only configuration/migration operations still parse; an actual production web-image build fails closed without it. Local npm/Compose fallback remains. The build marker is declared metadata, not a cryptographic build attestation. |
| Keep source-backed assertions and expiry behavior | Preserved. The far-future account/child expiry regression now seeds its cache with `canonicalOnly: false` to match `groupBrowse=1`; no expiry assertions were removed. |

**PR #189 closure recommendation:** the visual rework has no required product behavior left to port under the newer account-first contract. The missing production build identity guard was the concrete preservation gap; this follow-up restores it selectively with tests. Root retains responsibility for PR closure after integrated CI and independent review.

## Current customer workspace evidence

`run-native-ui.py` creates two fresh disposable databases from the repository’s Git blob bytes (preserving the source-manifest LF hashes), applies migrations, ingests the native retained-source adapter records with model use disabled, rebuilds saved browse, then launches the real API and web UI. Browser capture blocks all external requests. Only `DataBank` and `CyrusOne` are selected from the retained public-source corpus; the source file hashes, database names, build-source hashes and screenshots are recorded in [`run-native-ui-9/receipt.json`](run-native-ui-9/receipt.json). The before control uses only the pre-PR202 `saved_browse.py`; parser, retained source records, API/UI code and settings are shared.

- [Before: account list, desktop](run-native-ui-9/before-customers-desktop.png) — the stale control incorrectly presents first-seen historical facts dated 2024-09-10 and 2025-07-30 as “Recent development.”
- [After: account list, desktop](run-native-ui-9/after-customers-desktop.png) — current source omits both old events; actual IT load remains separately labeled, and unknown power need is not converted to zero or demand.
- [After: account detail, desktop](run-native-ui-9/after-databank-detail-desktop.png) — account projects are visible, commercial analysis starts collapsed, and no verified business contact or call/email route is asserted.
- [After: account list, phone width](run-native-ui-9/after-customers-mobile.png) — responsive list at 390 × 844 CSS pixels; no horizontal overflow.

The captured API rows use `canonical_only=true`, `shortlist=false`, and one published generation per view. Both modes used the same source-artifact hashes. Page errors and external requests were empty; provider calls were zero. Two public-source organizations are a technical readability fixture, not the 20-customer evaluation. Native evidence shows zero permitted contact routes for these two organizations. Therefore it demonstrates source-date honesty and current workspace rendering only; it does **not** establish verified buyer outreach coverage, outbound-sales usefulness, prioritization efficacy, or human acceptance. The owner-selected prioritization and verified-buyer-outreach goals remain subject to the wider current evaluation and real user feedback.

The API source-date is the effective backend source publication/event date. The card displays that date only when valid; it never substitutes observation or retrieval time. Regression fixtures assert the first historical fact stays absent while a supported dated revision appears with its exact source date.

## Deterministic checks

Executed against this worktree:

- `node --test deploy/validate-web-build.test.mjs` — Git clean/dirty/mismatch and Git-absent build metadata paths; compiled exact SHA acceptance/rejection; Compose/Docker wiring.
- `npm run typecheck --prefix web` and `npm run build --prefix web` — passed. Vite reports the existing large-chunk advisory.
- `npx playwright test --config=playwright.ui-followup.config.ts --grep="source-dated revision|cached browse context expires at the backend valid-until boundary|reduced motion preference"` — 3 passed.
- Production Docker build with explicit 40-character synthetic revision — passed preflight, compiled-artifact SHA check and postflight. This did not deploy or attest a release.
- `uv run --project backend python docs/validation/customer-intelligence-followup-20261113/ui/run_native_ui.py` — passed native before/after capture in fresh `gl3_ui_followup_*_test` databases; provider calls 0; web/API logs removed after successful capture.

The full integrated browser suite and independent review must run on the final integrated candidate. No production runtime, provider, salesperson or customer acceptance was tested here.
