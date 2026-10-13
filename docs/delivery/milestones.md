# Delivery milestones

This is the status page for current main. Other notes link here. Dated validation reports stay evidence for the commit they name.

Current main is `3f55750` (merge of pull request #49, Stage 3 recall, on top of `76a60fe`). Product acceptance is not that merge.

## Owner stages and PRD milestones

The owner's sequence is S1 through S7. The PRD exit gates are A through E. A completed stage is not a closed PRD gate.

| Stage | What it covers | PRD milestone | Status |
|---|---|---|---|
| S1 | Documentation baseline | Not an A–E exit | Complete. Pull request #47. |
| S2 | Bounded source-quality diagnostic | Evidence toward B. Not the B exit. | Complete as a diagnostic. Pull request #48. Not live-source acceptance. |
| S3 | Qualification recall and official RRC operator labels | Evidence rules used later by C and D | Merged in pull request #49 at `3f55750`. No Prospect or Lead was accepted. |
| S4 | One real end-to-end commercial pursuit | C and D | Open. Depends on a real pursuit, not on fabricating calls or promotions. |
| S5 | Canonical journey and owner visual acceptance | Presentation needed for E | Open. |
| S6 | Remove intelligence-to-HTTP coupling | Folder boundaries | Open. |
| S7 | PC-off scheduling, restore, alerts, and seven daily cycles | A and E | Open. Needs separate hosting, secrets, and monitoring authorization. |

## PRD exit gates

| Milestone | Required proof | Status |
|---|---|---|
| A — Foundation | A real scheduled source check persists an observation while the owner's PC is off | Open. API, worker, migrations, and auth exist. `deploy/scheduler.preparation.yaml` is suspended. `WORKER_AUTO_REFRESH` still plans inside the worker process. |
| B — Daily Signals | Real national and cross-industry observations, replay without duplicate cards, visible parser and source failures | Open. Local routes exist. Deployed daily breadth is not accepted. |
| C — Prospects | Correct identity and activity on reviewed records; unsupported utility uncertainty cannot promote | Open. |
| D — Leads | An auditable real Lead when evidence permits | Open. No real Lead is accepted. |
| E — Daily working release | Requirements 38–41, including backup restore and seven measured daily cycles | Open. |

Requirements 38–41 stay open until their evidence exists: live-source readiness, retained-sample qualification review, seven real consecutive scheduled operating cycles, and one independently discovered Lead reviewed by Nick. A source count, a test count, or a synthetic record does not substitute.

The dependency notes are in [the work graph](../../.agent/WORK_GRAPH.md). The short checkpoint is [current state](../../.agent/CURRENT_STATE.md). Stage reports remain dated evidence: [Stage 1](../validation/stage1-baseline-20261009.md), [Stage 2](../validation/stage2-source-quality-20261009.md), and [Stage 3](../validation/stage3-recall-20261009.md).
