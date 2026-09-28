# Current state

Owner direction: permits primary, rental generators and temporary/bridge power focus. Latest request: reduce duplicate project cards and replace permit-label headings with descriptions of the project/work.

Repository gl3; branch fix/project-cards; base a7ee3e4d22c5375481402c637d22c08eba59cbac. Prior GL3-006 through009 merged in PR2. GL3-010 accepted locally 2026-09-27T19:20:33.664338+00:00, uncommitted. Exact frontend candidate c1524aa5c876082f6b9968c8d8298e63e352d67d6f9c6d350e98234d9be8bb77; independent PASS artifacts/GL3-010/REVIEW-r3.json. Prior FIX receipts and state retained.

Presentation grouping combines19 matching Zilker event permits into one card;32cards cover all50records. Each member keeps individual evidence and detail access; member-ID search preserves the group. Other sites, tiers, activities, descriptions and dates remain separate. Bold permit headings derive from source work descriptions; sparse descriptions fall back to activity and location. No database/backend/source/qualification changes.

Validation: web typecheck/build, all3 Playwright tests, diff check, authenticated live32cards/50records/19members, permit search,390px no overflow and zero page errors. Controller receipt artifacts/GL3-010/CONTROLLER_VALIDATION.json. Local API8000 and Vite5173 remain running. No new push/merge/deploy performed.

Canonical docs/product/PRD.md and WORK_GRAPH.md govern. Parent Finish Contract OPEN, national coverage OPEN, cloud deferred. Grouping is conservative presentation only, not full durable project-entity matching. Next direction: user testing of local display; preserve individual power activities and evidence in future consolidation.
