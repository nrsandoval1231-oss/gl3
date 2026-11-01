# Customer rollup performance repair — November 1

Authority: owner-approved default grouping repair, continuation and existing draft PR163 publication. Production deployment held after valid DE CENTRAL HTTP timeout. No merge or database/schema/security changes.

Goal: remove repeated whole-sector work from group opening while preserving default customer grouping, full-set filters/counts/stable pagination, all child pages, exact identities and privacy-aware serialization. Keep HTTP deadline 15 seconds.

Ownership: backend builder owns customer_results.py, api/app.py and scale integration fixture/tests; browser builder owns web/acceptance/rollup-scale and dedicated config; profiler owns sibling diagnostic script; lead owns packet/docs/runtime/evidence; Astra reviews independently. No shared database execution by builders.

Acceptance: representative retained-snapshot SQL and HTTP timings with honest cold/warm labels; 2,098-row/417-group deterministic endpoint regressions; actual backend browser journeys at three viewports; full repository required gates and independent exact-final review. Explicitly report unavailable measurements. Synthetic data cannot establish live production acceptance.

Publication: scan intended diff for private data/secrets, push validated correction to existing PR163, monitor exact-head required CI and update truthful summary. No raw retained archives in repository. Deployment remains held pending separate release gates and any specific new privileged controller approval.
