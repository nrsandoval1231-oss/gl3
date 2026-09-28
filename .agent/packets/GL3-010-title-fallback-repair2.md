# GL3-010 title fallback repair 2

Repair-only packet after `FIX` in `.agent/artifacts/GL3-010/REVIEW-r2.json` for candidate `c2a6198dc017ec6f8d82bb161b418ba5444d33cfd395ca7e1a18016be358f18c` on `fix/project-cards`.

Change only `web/src/features/opportunities/projectCards.ts` and `web/tests/project_cards.spec.ts`. Preserve both prior reviews, the grouping rule, and the retained 50-row behavior. Structured permit abstracts may supply only a substantive `description` field as a fallback; ignore `work`, `project`, `type`, row/date/status, and generic labels such as `New` or `Building Permit`. A missing or generic description uses neutral activity plus location. Preserve substantive `supported_action` text.

Add focused coverage for an abstract containing `work: New` and `type: Building Permit` without description. Run the focused Playwright regression and frontend typecheck; then hand off for controller exact-candidate gates and independent review. No app layout, runtime, database, grouping, or other changes.
