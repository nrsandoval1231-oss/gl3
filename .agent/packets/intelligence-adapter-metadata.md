# B7c — preserve billing metadata across paid adapters

Base: rejected9391984ea3899318df7eab5c2946e075cc48d6c9, isolated
feat/intelligence-integration-20261018. Dependency: independent exact-source FIX.
Terra owns intelligence_provider.py, legacy_calls.py, signal_adjudication.py,
briefs.py only if needed, and focused provider/worker/brief/Signal tests. Root owns
control documentation. Luna's browser diagnosis is disjoint. No schema, UI,
commercial gates, external requests, activation, push or deployment changes.

Require object-valued structured OpenAI output through the shared transport, with
received-response metadata retained on rejection. Distinguish absent/null usage
from present malformed usage for OpenAI and TypeSafe legacy results. Preserve
ProviderResponseError billing metadata through JevError without introducing a
retry. Valid exact-model NULL measurements under verified bounds remain supported.
Do not label semantic invalidity alone as a demonstrated billing overrun.

Validate actual adapter-to-ledger behavior with synthetic PostgreSQL tests:
non-object brief output with mismatched/over-bound billing metadata; malformed
usage variants; valid NULL controls; TypeSafe wrapper errors with one invocation;
durable provider hold blocking fresh and reserved calls. Retain failed receipts.
Two materially different repair attempts, then report the actual constraint.

Adjacent bounded test ownership: test_acquisition_runtime_bounds.py immediate
queued fixtures. Reproduced OCR admission test returns no eligible job with
default database-clock availability. Verify before changing fixtures; explicitly
past availability is allowed only where immediate eligibility is intended. No
production clock or timeout relaxation. Dedicated settlement test/app database
only. Root final test database remains isolated.

Handoff: exact files, commands, terminal counts, UTC and limits. Root reruns full
gates with --maxfail=1 on a fresh clean commit; this selects all tests and fails
early on rejection. Independent source review and runtime/restore/browser proof
remain required. Parent operational acceptance remains OPEN.

Handoff:93 focused tests pass in28.15s;7 acquisition tests pass in3.57s; scoped Ruff/mypy/diff pass. Product changes limited to shared provider/legacy/Jev adapters. Brief mismatch/over-bound non-object response and actual Jev wrapper each have durable quarantine tests; single invocation/no retry. Explicit past availability changes only immediate test fixtures. No provider requests.
