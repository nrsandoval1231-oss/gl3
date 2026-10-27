# Backend API client

Use generated contract types and a thin client. Keep authentication and authorization enforced on the server. The customer-facing client exposes read-only search, opportunity, evidence, contact, buying-chain and autonomous research projections; it does not expose manual call logging, fact drafting, operator status, contact corrections, pursuit notes or research submission controls.

Current project browsing uses `client.projectResults`: an authenticated prepared physical-project result with exact sector/count/cohort semantics and optional canonical `need_id` read. `ProjectResults` uses the default qualified scope and explicit sector/search discovery; the project Overview refreshes the exact prepared result before exposing contact controls. Existing need detail, account, Signals and Research clients remain secondary. See [the prepared project contract](../../../docs/architecture/PROJECT_RESULTS.md).
