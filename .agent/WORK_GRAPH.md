# Work graph — approved Opportunity Intelligence UI

Authority: [APPROVED-UI packet](packets/APPROVED-UI.md). Prior graph bytes remain in archive/APPROVED-UI/pre-WORK_GRAPH.md. One dependent builder path; no artificial parallel implementation.

| Node | Candidate checkpoint | Dependency | Owner | Evidence |
|---|---|---|---|---|
| UI1 screenshot reproduction | IMPLEMENTED | PR102 base5ef5f3f | Luna, bounded Terra recovery | Source manifest and completion receipts |
| UI2 runtime/comparison/gates | VALIDATED locally | UI1 | Controller | docs/validation/approved-workspace/CANDIDATE.md |
| UI3 exact-candidate independent review | NEXT | UI2 frozen commit | Fresh Sol | Ignored REVIEW.json/REVIEW.md bind verdict to exact commit |
| UI4 focused stacked draft PR | WAITING on UI3 | UI3 | Controller | Delivery receipt binds pushed SHA, PR and CI separately |
| ASSET1 licensed Diatype / official master | EXTERNAL DEPENDENCY | Owner assets | Owner | Images available; font binaries absent |

Next direction VALIDATE UI3. Subsequent review/delivery receipts record graph transitions without extending audit coverage to changed source. Failed attempts remain under ignored .artifacts/approved-ui/attempt1, attempt2 and attempt3; setup/persisted failures also retained. Bounded technical acceptance cannot close ASSET1, PR102's broader gates or the parent Finish Contract. No merge or deploy authority.
