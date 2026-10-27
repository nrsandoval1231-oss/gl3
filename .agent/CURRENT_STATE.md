# Current work — operator/customer hierarchy and current-data recovery

Owner request (2026-10-27): repair bulk-contact over-redaction; establish safe rollback for current production data; test, independently review, merge and deploy without activating paid providers. Operator/customer is primary, with every supported well/project nested underneath. This supersedes the earlier project-primary presentation. Qualification, identity, evidence and privacy rules remain intact.

Branch: `fix/operator-customer-recovery-20261027`, base `20c47ee4acdbd574051c1f85b1e6a6869ba2bde1`. Implementation is isolated from unrelated local-auth changes in the primary checkout. Previous state is preserved verbatim in [the archive](archive/OPERATOR-CUSTOMER-20261027/previous-current-state.md).

Four Luna builders own privacy, grouped API, grouped UI and guarded recovery. Astra reviewed recovery architecture with required publication/CAS and provider gates; final integrated implementation review remains required. Assignments are not verification evidence.

Acceptance and next steps: [release protocol](../docs/validation/operator-customer-recovery-20261027/PROTOCOL.md). Reproduce bulk over-redaction, retain fail-closed per-project privacy limits, and test non-vacuous suppression. Group the full cohort on stable identities with bounded child pagination, typed dates and distinct project contacts. Recovery stages an invisible generation and publishes only under exact revision/pointer/policy guards while writers are held; no obsolete-pointer override or production snapshot restoration.

Disposable PostgreSQL 18 and Python 3.11 are available with external-test network guards and no paid keys. No checks for this candidate have yet been accepted. Production was observed on the base revision with schema `0047_scoped_identity_link_browse`; source reconciliation and fresh backup/isolated recovery proof remain required. Commercial P0 remains unmet.
