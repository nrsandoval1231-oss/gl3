# Environment continuity slice

Based on main `298bc40c3ab88789bb1bb6e9f714c551d34b29c9` (fetched October 14,
2026). No open PRs or uncommitted work existed at start. No backend, ingestion,
database, dependencies, qualification rules, or visual system changes.

## Behavior

- Lens, tier, and search preserve geography, selected need, and working mode.
  Excluded selections remain explicitly separate from matching results/counts.
- Selected records resolve using the existing authenticated need endpoint without
  a browse scope. A separate scoped lookup checks membership; neither uses the
  map's four-page cap. The endpoint still enforces opportunity eligibility.
  A 404 means unavailable/deleted/no longer eligible; it does not prove deletion.
  Authentication, request errors, and filter exclusion have separate messages.
- Browser history carries scene identity and UI snapshots, not server records or
  call input. Back/Forward restores scroll (including state lists), focus, menu,
  and disclosures, waiting for dependent content. Existing state focus determines
  the map transform; no new pan/zoom behavior was added.
- Call input, saved draft IDs, and exact-payload idempotency keys live separately
  under need ID. Navigation never writes facts. Saving drafts and accepting facts
  remain separate explicit operations. Another call can begin without accepting
  saved drafts, which remain in server fact history.
- Refresh and full-document legacy visits use bounded tab-local session storage,
  expiring after eight hours and cleared on logout. Storage is capped at 40
  entries / 2,000,000 UTF-16 code units; navigation can evict only navigation
  snapshots, never call input. A full draft budget visibly disables refresh
  protection for the new write. Interrupted saves report an
  unresolved request and retain retry keys. Storage failure is visible in the
  call form. Legacy routes retain an explicit Return to environment link.
- Errors have a retry control; Source health opens the existing health panel.

## Reproduction and verification

Browser reproductions before fixes showed: selected need p204 missing from a
205-record fixture; tier changes clearing action/need/state; call input lost
across Back/Forward; absent retry and Source-health destination. Review-driven
reproductions also caught missing async disclosure/menu restoration and no way
to begin another call. All fixture names and input exist only in tests.

Checks run:

- `npm --prefix web run typecheck`: passed.
- `npm --prefix web run build`: passed.
- `git diff --check`: passed.
- Final affected browser run (`environment.spec.ts`, `call-facts.spec.ts`,
  `buying_chain.spec.ts`, `project_cards.spec.ts`): **86 passed, 1 existing skip**.
- Full `npm --prefix web run test:ci` run before the final storage-boundary
  regression: **111 passed, 1 existing skip, 1 failed**. The real-session auth
  test received HTTP 500 during login; API logs show PostgreSQL connection
  refused at 127.0.0.1:5432. This is not a passing auth acceptance result.
- No backend API or implementation changed; backend tests were not rerun.
- Desktop (1280px) and mobile (390px) rendered fixture journeys, keyboard
  navigation and reduced motion passed; screenshots were visually inspected.
  Existing desktop tests also exercise default motion and rapid navigation.
- Independent code review findings were addressed and regression tested.

[Desktop fixture screenshot](desktop-fixture.png) ·
[Mobile fixture screenshot](mobile-fixture.png)

Screenshots are rendered fixture journeys, not real-data acceptance or canonical
visual comparison. No production deployment was performed.

## Local startup

From `backend`, run `uv run uvicorn gridlens.api.app:app --host 127.0.0.1
--port 8000 --no-proxy-headers`. From `web`, run `npm run dev -- --host
127.0.0.1 --port 5173`, then open http://127.0.0.1:5173/ . The existing configured
PostgreSQL service and authentication configuration must be available to use
real data. No database was created or migrated by this slice.

## Limits and next slice

The configured local PostgreSQL service at 127.0.0.1:5432 was unavailable. A real
retained opportunity and persisted call journey therefore remain unverified.
Do not treat API-intercepted browser tests as proof of live-data acceptance.

The exact canonical PNG (SHA-256 077b2767…e501ecc) and HTML (6274e701…486b2e)
were not found in the workspace, home, temporary files, or main's reference tree,
including ignored-file and exact-size searches. No replacements were generated.
Visual fidelity to these originals remains unverified.

Next slice: bring browsing and commercial pursuits into this canonical
navigation environment, preserving independent tier, rank, disposition, workflow
status, and retained evidence. Reuse this restoration/draft model rather than
consolidating the whole shell in one change.
