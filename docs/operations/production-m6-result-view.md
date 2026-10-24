# M6 saved commercial assessment view

The opportunity detail's Commercial Assessment tab reads the authenticated intelligence history for that exact power need. It renders only completed `COMMERCIAL_ASSESSMENT_V1` results with `VALIDATED` outcome. Unknown, stale, blocked, and failed jobs show their saved status and reason without an assessment summary.

The history API adds a bounded `commercial_assessment_support` projection. It joins selected fact IDs from the job checkpoint to the same checkpoint's exact package, checks the package digest and package row's need/project identity, and rechecks retained evidence ID, hash, observation relation, source URL, field and text span. It returns only selected facts and citation excerpts. A source context still matching the saved request is labeled `current`; a retained historical context is labeled `saved`; failed checks return `unavailable` with a reason. The projection does not change the saved assessment or full checkpoint.

The UI keeps disposition advisory, preserves unknown fields and document/source coverage, and places call/job/usage detail under a disclosure. Selected facts with unavailable support do not receive a source link. Provider outcome `UNKNOWN` explicitly states that retry is blocked pending reconciliation.
