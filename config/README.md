# Source and policy configuration

`config/sources/registry.v1.json` is the repository's versioned source declaration. It describes configured policy and endpoints; it does not prove a source is enabled in the production database, recently fetched, or successfully parsed. Use [source coverage](../docs/sources/coverage.md) for the dated observed state.

Qualification, ranking, and operating limits belong in their reviewed config/code authority. Credentials, runtime records, and provider receipts do not belong here. The runtime settings model is documented in [runtime configuration](../docs/operations/runtime-configuration.md) and implemented in `backend/src/gridlens/settings.py`.
