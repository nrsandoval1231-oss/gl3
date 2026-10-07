# GL3-029R1-TYPE: mandatory typecheck portability repair

READY dependent repair after R1 focused handoff. Base PR24 d8b0e998; same isolated repair worktree. One Luna owns only backend/src/gridlens/ingestion/adapters/bounded_http.py, directly relevant existing isolation tests if needed, and docs/operations/research-recovery.md explanation. Not alone; preserve controller documents and previous repair.

Evidence: unrestricted `mypy src` on Windows fails two attr-defined errors for resource.setrlimit/RLIMIT_AS; raw ../gl3-repair-evidence-20261004/mypy-preflight.log. Scoped error suppression is NOT accepted. Retry budget two materially distinct attempts.

Use a bounded platform-neutral optional-module loading method (existing importlib is available) without disabling mypy errors or changing limits, timers, subprocess fences, acquisition contracts, or installing new infrastructure. Preserve Linux 512MiB enforcement and explicit fail-closed acquisition on platforms without resource support. Do not pretend Windows resource isolation is proven or replace the limit with an unbounded fallback.

Acceptance: unrestricted backend `mypy src`; focused existing bounded_http/isolation tests; no admission/budget/provider changes. Record unsupported Windows acquisition as explicit limitation, not a healthy provider outcome. Supply raw logs and separate ignored completion artifact. No paid/provider calls, remote writes, runtime credentials, cleanup or source expansion. Root freezes after handoff and reruns exact-candidate mandatory gates.
