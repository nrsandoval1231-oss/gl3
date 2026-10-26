# Contact suppression rollback contract

Migration `0045_contact_suppressions` retains privacy controls in an append-only ledger. Never delete or downgrade this ledger as part of an application rollback.

Application images built before suppression support do not read the ledger and can expose methods that the current image hides. A rollback is permitted only after deploying a compatible image that reads the ledger across contact search, opportunity, company, project, history, import, and refresh surfaces. Otherwise keep those contact surfaces and refresh workers disabled until a compatible image is available.

Retained source evidence and correction history remain immutable for audit. The privacy overlay applies to structured contact reads; it must not rewrite or delete those records.
