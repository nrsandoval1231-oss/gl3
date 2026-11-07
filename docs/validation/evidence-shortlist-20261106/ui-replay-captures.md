# UI replay captures

These screenshots are local UI replays against frozen copies of actual source-backed project results. They do not show a live production session.

- `ui-before-*` uses the frozen baseline UI at `fc59eab6` and the first 25 rows from the 2,258-project All Projects source-copy response.
- `ui-after-*` uses the current local UI and the first 25 rows from the final 41-project shortlist SQL replay.
- Both capture fixtures omit contact routes and contact people. The after fixture also replaces one source-attribution personal name with `[personal name omitted]`; the original private payload is unchanged.
- The same five desktop, tablet, and mobile viewports were used for both captures: 1648×928, 1440×900, 1280×800, 768×1024, and 390×844.
- Frozen responses were replayed through local API route mocks. No production writes or provider calls occurred.
- Both replays use a synthetic unavailable equipment-summary response with counts_complete: false and the limitation Equipment summary not computed in this frozen replay; it displays no equipment MW or equipment-demand record-count measurement. The 2,258 and 41 project-cohort totals come from the frozen project responses.
