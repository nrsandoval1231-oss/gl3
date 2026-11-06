# Retrospectives

## 2026-11-06 — feat/commercial-workspace-ux
**Shipped:** four-section nav; Opportunities cards; owner-managed Pursuits (backend migration 0050 + frontend); Companies directory and Reports with honest metrics; detail panel restyle; canon docs amended.

**Not done / known limitations**
- Production is at 0049; migration 0050 is not applied anywhere.
- No confidence data exists, so the reference design's Confidence is omitted.
- Companies directory has no Total MW or linked-pursuit columns (groups endpoint lacks them). Group counts include unresolved/same-name groups, so they are labelled "operator/customer groups".
- Browser Back/Forward into a panel can refetch need detail behind the hidden Opportunities page.
- `auth.spec.ts` needs a real backend and `GRIDLENS_TEST_PASSWORD`; locally it fails at its own guard ("Set GRIDLENS_TEST_PASSWORD to the password for the disposable test API"). In CI the `browser` job runs `npm run test:ci` with a real backend and `GRIDLENS_TEST_PASSWORD`; that step passed before the later seed step failed on a pinned-revision guard (fixed by commit 4f59f27).
- Screenshots were compared with the references by eye only.
- A one-press Back for "Back to Opportunities" was reverted: an existing test expects browser Back to reopen the panel.
