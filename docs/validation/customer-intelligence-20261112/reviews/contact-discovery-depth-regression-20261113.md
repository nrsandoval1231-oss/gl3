# Contact research depth regression and bounded repair

This is local disposable-database evidence, not production verification. Existing tests are unchanged.

## Reproduction

An isolated run of `tests/integration/test_buying_chain.py::test_membership_only_company_contact_job_keeps_unverified_domain_unresolved` failed on both main `5ee2f30c2b1c9998063db1c6468d1f4e65f7ac2d` and the integrated working tree. Both runs used the same Python environment, Beautiful Soup 4.13.4 and Soup Sieve 4.0. The main checkout's lock differs; this is a matched-runtime source comparison, not a claim about every main CI run.

Both returned three checked URLs instead of the asserted four: homepage, corporate contacts and leadership. The unchanged depth heuristic counted contacts and leadership as two pages without verified contact yield and stopped, despite the leadership page containing a concrete relevant named-role lead. No canonical domain or contact was verified. The separate two-empty-pages test deliberately requires that stop for pages without new named roles.

Private command/log receipts: `/workspace/task-runtime/contact-baseline-regression.log` (main, one failed), the dedicated contact-review run reported by the builder (136 passed, one failed), and `/workspace/task-runtime/contact-depth-final-tests.log` (repair, ten passed). All databases use task-owned loopback names ending `_test`; no retained or production database was used.

## Change and checks

The discovery heuristic now keeps a separate person/title hint set. A newly observed relevant named role permits continuing within the existing fixed URL, HTTP, lease and deadline bounds. Repeated hints across URLs, stale/future observations, historical/denied roles and generic organization methods do not extend depth. Existing verified-contact yield, success status, identity reconciliation and publication guards remain authoritative. A hint never becomes a verified contact.

Commands from `backend/`, after loading the private disposable environment:

```bash
.venv/bin/ruff check src/gridlens/intelligence/company_contact_discovery.py tests/unit/test_contact_role_discovery_hints.py
.venv/bin/ruff format --check src/gridlens/intelligence/company_contact_discovery.py tests/unit/test_contact_role_discovery_hints.py
.venv/bin/mypy src/gridlens/intelligence/company_contact_discovery.py
.venv/bin/python /workspace/task-runtime/run_mission_checks.py .venv/bin/python -m pytest tests/unit/test_contact_role_discovery_hints.py tests/integration/test_buying_chain.py::test_membership_only_company_contact_job_keeps_unverified_domain_unresolved tests/integration/test_buying_chain.py::test_contact_discovery_stops_after_two_official_low_yield_pages -q
```

Ruff and mypy passed. The final targeted run passed **10 tests** in **22.25 seconds**, including both existing journeys without modification. The measured module SHA-256 is `0d6f04d4dd4af26fdd038f5133075394ef2d32bf6c46d5aeaef0e1fd94f38931`. A later source change requires another check. Full integrated CI and independent implementation review remain separate gates.

## Rollback

Revert the heuristic and its additive helper; no schema, provider setting, source activation or stored contact identity was changed. That restores the reproduced research-depth limitation and does not change the independent contact publication boundary.
