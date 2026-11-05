# Current owner request — ingestion strategy and live intelligence build

The November 2 progress reconciliation is complete; its request is preserved in Git history and the [release receipt](../docs/validation/production-release-20261102.md).

The owner now asks for the new ingestion strategy and live intelligence to be built. The full brief, including owner decisions and authorizations, is the [Claude Code handoff](../docs/strategy/ingestion-handoff-20261103.md). The plan it implements is the [ingestion strategy](../docs/strategy/ingestion-strategy-20261103.md), with supporting [research](../docs/strategy/ingestion-research-20261103.md).

Authorized by the owner on 2026-11-03:

- Implementation of the handoff's workstreams, one branch and PR at a time, with the full [finish contract](FINISH_CONTRACT.md) gates.
- Paid providers under a combined $100/month cap: TypeSafe Jev (live, with the tiered authority in the handoff), OpenAI `gpt-6.1-sol` for grounded proposals, and paid OCR. Keys are already in Infisical; never print or commit them.
- A canon update giving Jev the bounded live authority described in the handoff.

Not authorized without separate owner confirmation: production deployment, credential changes, new infrastructure, destructive data actions or history rewriting. Prepare production configuration changes as a list for the owner to apply through the protected release process.

First session scope: workstream 0 (prepare the production env changes) and the workstream 1 twenty-document spike, then stop and report before building the extraction core.
