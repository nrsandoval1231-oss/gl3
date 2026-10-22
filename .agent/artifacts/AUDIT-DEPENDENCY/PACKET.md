# AUDIT-DEPENDENCY

Node: AUDIT-DEPENDENCY-CERTIFI
Base: f2b644c4d93c17c04e590c5bd19cfa197a5b41bb
Branch: repair/audit-certifi-20261020
Scope: backend/uv.lock only for the source change; this artifact directory for evidence.
Objective: resolve GHSA-6q48-6c7w-9gw2 by updating certifi to 2026.10.19 with no package version changes beyond certifi.
Validation: `uv lock --upgrade-package certifi==2026.10.19`; `uv sync --locked --extra dev`; `uv export --locked --extra dev --no-emit-project --format requirements-txt --output-file .artifacts/backend-requirements.txt`; prescribed `uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r .artifacts/backend-requirements.txt --disable-pip --no-deps --format json`.
Acceptance: locked sync succeeds and audit reports zero known vulnerabilities. Root owns repository full gates and exact-candidate review.
