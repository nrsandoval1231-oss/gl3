# PR126 suppression repair and bounded commercial follow-up

Status: engineering accepted. Owner explicitly authorizes release despite unmet commercial targets. Production deployment is performed separately through the existing authorized desktop connection.

## Integration boundary

The prior PR126 remote candidate was `27f7400278e3c3054b3cb7dfdcb45dd4fb859af0`. Main's PR123 merge `6a6551d` was reconciled locally in `7498efc` (`[skip ci]`). The Windows patch archive was not materialized or applied here. Repairs were independently implemented from the textual handoff against the current code, with local regressions and review. No new GitHub Actions were started.

The continuation repairs privacy projections and internal refresh comparisons. Immutable evidence and saved snapshots remain stored; suppression applies to read responses. It does not add manual qualification, feedback, or logging workflows. No schema migration is required by these repairs.

## Repair scope

- Refresh and retained-contact comparisons read internal claim state rather than privacy-redacted public output. Public responses still enforce suppression.
- Current buying-chain views retain historical identity scope across refreshes; permit summaries resolve parties from immutable claim citations and retained evidence, independently of already-redacted visible candidates.
- Saved-history page/detail responses use one deep-copy projection for latest and historical versions, former grouped members, legacy contacts, source passages, and saved notes. Scoped and global ledger keys are bounded, and ambiguous or excessive scope fails closed.
- Contact-token overflow redaction preserves engineering facts and ordinary citation URLs. Company/person suppression does not mutate evidence or saved snapshots.
- Successful company research now retains a stable source/request identity for immediate replay, so its own improved contact gaps do not schedule duplicate work. Changed needs, sources, generation, or gaps still invalidate the completed outcome.
- PR123's tests now distinguish unsupported text-only pages from parser-confirmed person cards on official pages, matching the retained PR126 extraction policy.

Final validation: **3,175 passed, one optional skip**, covering all3,176 collected tests through an interrupted ordered passing prefix plus disjoint isolated partitions and reviewed focused reruns. This was not a single uninterrupted full-suite pass. Ruff/format (380 files), mypy (174 source files), documentation links, web build/typecheck and two focused desktop/mobile checks pass. The prior124 full browser/auth checks remain dated evidence; they were not rerun or relabeled as production checks.

See [machine-readable coverage](backend-coverage.json), [verification](verification.json), [raw validation receipts](validation-receipts.tar.gz) and [independent acceptance](independent-review.md). The temporary runner's three spawn-related timeouts were resolved by a main guard and clean reruns; one unsupported foreign-project contact assertion was corrected after independent review. No production source change followed the frozen candidate.

## Commercial evidence

[The gap matrix](cohort-gap-matrix.md) and [machine-readable records](cohort-gap-matrix.json) cover bounded follow-up of all 25 frozen benchmark records. [Retrieval receipts](cohort-source-retrieval.json), [search receipts](upstream-search-receipts.json), and [the RRC probe](rrc-query-probe.json) preserve source-access outcomes. Public retrieval works; production authentication is a separate unresolved requirement.

Strongest improvements:

- Rice: a city-hosted presentation publishes Dennis Finster's business email; the company site identifies him as CEO. Project schedule/phase conflicts remain. This does not verify mailbox deliverability, procurement authority, or temporary demand.
- Beacon Point: Hut 8 publishes a company project-inquiry email; official sources identify Jacobs EPCM scope and target energization/delivery milestones. These are not named-person methods or a confirmed rental gap.
- Pecos: Amazon describes planned on-site generation and eventual grid transition. Electrical shortfall, rental MW, duration, and current procurement are unknown.
- Circle T: PowerHouse confirms developer context and campus scale. Exact legal-entity/phase binding and reachable procurement contacts remain unresolved.

The 21 upstream records remain unqualified for temporary power on this follow-up. Secondary API numbers, locations, and spud dates are research pointers, not verified electrical demand or power-needed dates. Adjacent wells were not merged. No benchmark scores or canonical records were changed.

## Release boundary

See the [exact owner release exception and deployment handoff](release-gates.md). The October26 17:55UTC instruction overrides the commercial merge/deploy gates for this release; code-safety and essential operational safeguards remain.

The latest October26 17:55UTC instruction supersedes the earlier conditional commercial release boundary. Merge follows completed code-safety validation and independent engineering acceptance; production execution still requires existing access and essential backup/rollback/live safeguards.

No workbook activation, paid-provider calls, production writes, merge of PR126, or deployment occurred in this continuation. The frozen benchmark still does not demonstrate the declared commercial acceptance thresholds. Authenticated production access, observed deployed revision/schema/counts, backup and rollback readiness, and essential authenticated live verification remain unproven deployment safeguards. Engineering regression success does not close them.
