# Implemented architecture and evidence boundaries

Observed in the repository at commit `8163f134d87eb92a19fbe18824630cb97490d15e` on 2026-10-20. Product behavior remains governed by the [PRD](../product/PRD.md); the October 20 owner-approved Pursuit Workspace remains governed by the [UI canon](../design/UI_CANON.md).

The implemented stack contains a FastAPI backend, separate Python worker, React/TypeScript web application, and PostgreSQL persistence. Retrieval/parsing lives in source adapters; evidence interpretation and qualification live in backend services; the web app presents server-owned state. Generated TypeScript API types come from the backend OpenAPI contract. The current code also contains versioned attributed need facts and decisions with deterministic reassessment, separate from workflow-status events.

Known coupling remains: `intelligence/commercial_evaluation.py` and `intelligence/autonomous_research.py` import projection functions from `api/app.py`. The original Stage 6 extraction proposal is not proof that the extraction occurred; the coupling is still present in code as inspected for this document. Do not report that Stage 6 is complete based on the old overview or delivery notes.

Project identity, each power activity, evidence, qualification tier, supply assessment, buyer role, and workflow state remain distinct. Unknown and conflicting inputs remain explicit. A source outage, generic contact, facility capacity, or missing utility response does not establish a power gap or Lead. Model output and user notes do not bypass deterministic qualification.

This overview describes repository code, not an active service or a released architecture. Production state is dated separately in [operations status](../operations/README.md). Detailed architecture notes are subordinate descriptions; confirm time-sensitive details against code. The September overview is preserved byte-for-byte in the [October 20 archive](../../.agent/archive/AUDIT-20261020/pre-docs-repair-8163f13__docs__architecture__overview.md).
