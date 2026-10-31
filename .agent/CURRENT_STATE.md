# Current checkpoint — customer rollup repair

CURRENT: owner approved local fix and validation for one default customer/operator entry with all supported projects nested, across Data Centers and Industrial/Oil&Gas. [Packet](packets/CUSTOMER-ROLLUP-20261031.md), [graph](WORK_GRAPH.md), [canons](../AGENTS.md). Branchfix/default-customer-rollup-20261031, basee0035d9e5bfb52f92bb4d21e6de0fac16d91adff. No PR publication/merge/deployment, migrations, normalization/backfill, providers or production writes.

The earlier Phase1 reliability candidate did not implement default rollup. Default route used flat project results; grouped and account routes were opt-in. Reuse evidenced identity/regulator-based group queries; do not merge unrelated entities by loose name. Search/filter/sort/count/pagination must operate server-side over the full customer cohort; nested projects retain individual identity/details/evidence/contacts. Conflicts/unresolved identities remain explicit.

Production prior593cfd5 restored and verified after release hold. Candidate cutover did not occur. Stale controller3858829 was identity-verified and retired bySIGKILL without resumption; preserved evidence remains outside this feature repo in task/release-preparation. Prior paired backup/restore/recovery proof passed for its exact artifact pair only.

NEXT: integrate three Luna lanes, validate disposable PostgreSQL18.6/backendPython3.11 + frontend build/browser suite, inspect retained AMAZON/PECOS,DECENTRAL/STORMCHASER,Diamondback read-only samples where available, and obtain independent Astra review. All final gates UNKNOWN until recorded.

Limits: earlier unexplained480s local timeout and ingestion catch-up gaps unresolved; no new release/readiness claim. Prior checkpoint bytes retained in archive/CUSTOMER-ROLLUP-20261031/.
