# Automated checks

`ci.yml` checks every push and pull request. The backend job creates disposable
PostgreSQL databases and generated credentials, runs lint/types, migrations and
backend tests, then runs the deterministic Playwright regression project and a
real authentication browser test. The web job audits locked dependencies,
typechecks TypeScript, and builds the frontend. Browser failure diagnostics are
retained for seven days.

Live-source acceptance requires populated source records and an active worker;
it remains a separate explicit check documented in `web/tests/README.md`.
