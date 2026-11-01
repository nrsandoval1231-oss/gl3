# Current checkpoint — November 1 reliability follow-up

Owner requested remaining issues be fixed after the audit and PR163 merge. This task continues that repair/deployment authorization. Production execution is still technically blocked: this workspace has no production SSH identity or remote execution capability. Do not confuse repository validation with live acceptance.

Baseline: main `9d3aedffea7b411a53d3b80bbf4a7c56c46f77dc`, PR163 merged. Candidate branch: `fix/remaining-reliability-20261101`.

Candidate changes: bounded, resumable RRC drilling monthly archive and flare submitted-date collection using existing durable progress lanes and unchanged worker continuation budgets; Texas-local date windows; authenticated demand summary from current validated equipment records in the current saved browse cohort; conservative physical-asset overlap exclusion; separate amount classes, unknown/conflict counts, and default-view KPI with session cleanup and periodic refresh. No migration or paid provider activation.

The demand summary is additional equipment input only, not total portfolio demand. It fails closed above its bounded candidate cohort and excludes unresolved overlapping needs. Flare bootstrap begins 90 days before first initialization, then resumes completed intervals after outages; drilling bootstraps from the month containing that same 90-day lookback and catches up closed months. Neither source continuously revisits completed historical windows for later corrections.

Validation and remaining limits: [repair receipt](../docs/validation/remaining-reliability-20261101.md). The previous checkpoint is retained in [history](archive/RELIABILITY-20261101/CURRENT_STATE.md). CI and independent review must pass for the exact candidate before merge. Production image build, fresh recovery proof, canary and authenticated QA remain required before deployment.
