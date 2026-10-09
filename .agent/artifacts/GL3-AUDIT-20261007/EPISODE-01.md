# Audit repair checkpoint — 2026-10-07 20:20 UTC

State: verified remote main `94c3acb7b36c6d5d04a77a0ec445e793e05120a4`; open draft PR28 and PR32 inspected. Ordinary recovery checkout and original databases/credentials preserved. Isolated worktrees and PostgreSQL cluster on loopback 55437 hold all mutable validation state.

Decision/action: reuse sound research PR28 changes, independently review before acceptance, implement security in a disjoint worktree, and inspect lifecycle support against an isolated retained backup. Canonical UI preview recovered with exact manifest checksum; screenshot and HTML remain unavailable.

Outcome/evaluation: A1 candidate `c6cbb92` rejected with FIX for outside-shortlist sibling grouping. Controller full suite: 1,241 passed, one optional skip, one Windows symlink-privilege failure. Core Ruff/mypy, frontend type/build/audit and migration repeat/drift passed. Extended Ruff found three pre-existing corpus script issues. A1-R1 and A9 packets retain these failures for repair.

A3 frozen `70136f774953d928f840d2ef3ef9595665a706a6` passed independent Sol review and controller 13-test authentication suite, full-source Ruff/mypy, fresh/repeated migrations and schema drift. Serially integrated into task branch at `ba3e8a1`; integrated full gates and real HTTPS topology remain pending. No deployment or external alerts.

Read-only retained corpus: backup SHA256 `828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886`; restored copy initially contains 16,960 Evidence, 1,168 Projects/PowerNeeds and 938 lifecycle events. Baseline Signal projection: 1,167 rows, 4,719 SQL statements, 7.364 seconds, 56,156,469 peak Python allocation bytes. One cold local process is not production latency.

Attribution/candidate lesson: an outside-shortlist test that stubs canonical reevaluation cannot prove same-work grouping. Proposed rule: reproduce with actual sibling needs outside the cap and the real grouping path. Metric: duplicate same-work planning entries must decrease from two to one while distinct-work entries remain. Promotion pending A1-R1 deterministic proof; reversible test/packet policy only. Requirements unchanged.

Next direction: CORRECT A1 after lifecycle handoff; complete independently validated A2/A9, then source controls and bounded API loading. Seven-day operation, source readiness, 30-discovery quality and owner-reviewed real Lead remain OPEN. UTC start, model config identity, root token usage and unmeasured phase durations are UNKNOWN; no speedup claim.
