# GL3-014 repair 2

Same isolated checkout/branch/base and protected boundaries as GL3-014. Preserve
REVIEW-r1/r2 and all prior evidence. Exact rejected controller candidate
f337f340ced4bf2bfb587096ef1a010912647959f679196f5d6a4c0c8e762cd9.

Implement only the two findings in REVIEW-r2.json: select one complete current
accepted evidence-bound supporting claim deterministically for each shared
project/activity need, preserving its tier/MW/supply/rationale irrespective of
arrival order. Never assemble partial claims into Prospect. Recompute after
withdrawal/correction so stale Prospect facts cannot survive without support.
Qualification code remains unchanged. Test both Signal/Prospect arrival orders,
qualifying-source withdrawal, retained attribution, and exact replay stability.

Reject address-based matching when RSS contains multiple distinct explicitly
labeled sites. Persist an ambiguity reason and keep the record separate. Repeated
identical address mentions may represent one site. Add an actual RSS ingestion
regression for two distinct sites; retain existing positive cross-source case.

One Luna, no subagents. Allowed: ingestion/service.py, intelligence/project_identity.py,
focused existing tests, relevant validation explanation if needed. No schema,
API, adapters, qualification, UI, or CI changes unless return concrete blocker to
controller. Dedicated gl3_pr4_suite_test at127.0.0.1:55434 exclusively builder until
handoff. Controller owns history database, external actions, and final gates.
Run focused tests, Ruff, mypy, full217+ backend suite before handing off compact
COMPLETION-r3.json. Do not grade/commit/push/merge. Freeze code after handoff.
This is the second materially distinct bounded repair. If unresolved, return to
canonical intent and escalate the constraint rather than retry unchanged.
