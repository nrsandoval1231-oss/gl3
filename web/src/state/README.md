# Tab-local continuity

`sessionState.ts` bounds temporary navigation snapshots and call input in session
storage. This is not a domain cache or a persistence API. Entries expire after
eight hours and logout clears them. Browser storage can be denied; the call form
reports when refresh protection is unavailable.
