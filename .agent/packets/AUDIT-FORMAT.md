# AUDIT-FORMAT packet

Objective/node: satisfy the mandatory Ruff format gate on integrated, released backend surfaces without semantic changes. Base source a60b6fd60f562a1031baa5e0a729f737ef627ad7; controller supplies exact packet commit/worktree. READY: CORE and RETAINED/Terra terminal; UI still owns app.py and must not be touched.

Ownership: backend/src/gridlens/intelligence/buying_chain.py; backend/tests/integration/test_call_fact_workflow_integration.py; backend/tests/integration/test_pursuit_workspace.py; backend/tests/integration/test_saved_browse.py; own completion artifact only. Exclude app.py, all news/ingestion changes, web, migrations and docs. Other builders work concurrently; preserve their edits.

Action: run locked Ruff formatter on only these four files. Confirm Python ASTs before/after identical, lint these files and git diff --check. No semantic repair or new tests required for deterministic formatting. Retry budget one; stop and return evidence if AST changes. No external action, database or provider calls. Commit changes and .agent/AUDIT-FORMAT-COMPLETION.json with base/source SHA, commands/exits, UTC timing, unknown tokens/config and no acceptance claim. Controller integrates serially; later publication optimization is a separate packet after UI migration joins.
