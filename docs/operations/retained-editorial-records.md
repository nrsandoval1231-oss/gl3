# Retained historical editorial records

The editorial review workflow has been removed. Its six API routes, review UI,
assessment logic, export command, and feed consumer contract are no longer
available. Old `/` links using `?view=editorial` have no supported editorial
scene and fall through to the private Pursuit Workspace.

Migration `0019_editorial_decisions`, the `editorial_decisions` and
`editorial_assessments` tables, their ORM mappings, and their browse-invalidation
registrations remain unchanged. Existing rows are retained as historical data;
there is no editorial review or clearance API for reading or changing them. The
tables remain part of normal database backups and restore procedures.

PR #71 is superseded. Separate newsletter PRs #72 and #73 are unchanged and
unmerged. Their current branches depend on the removed editorial eligibility and
URL helpers, and PR #72's migration `0020_market_newsletters` conflicts with
main's `0020_evidence_source_provenance`. They need an independent rebase and
scope decision before future integration.
