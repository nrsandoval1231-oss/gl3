# Tab-local continuity

`sessionState.ts` provides bounded, expiring session-storage helpers for temporary navigation state. It is not a domain cache or persistence API. Entries expire after eight hours, storage failures are handled, and logout clears GridLens entries. No manual call-entry workflow is supported.
