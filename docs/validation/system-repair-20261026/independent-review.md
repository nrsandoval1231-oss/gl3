# Independent commercial-repair review

Reviewer: Astra independent review agent. Date: 2026-10-26.

Reviewed source: `9316c36`, against retained PR126 baseline `7e5179f`. Integration head `4a4db68` adds staging-report documentation only. Earlier focused test execution was at `7954e29`; subsequent findings and source readbacks are recorded below. This review follows the owner's exceptional-control clarification and the updated Autonomous Intelligence Canon. It does not supersede the separate deployment and commercial-evidence holds.

## Review result

**No remaining blocking implementation finding was identified at source `9316c36`. Final regression acceptance remains pending the exact-source full backend and browser gates.** This supersedes the changes-required result at `993b6c7`. The interrupted full-suite runs at `7954e29` and `993b6c7` are not passing acceptance evidence. Source review is complete for starting the final gate; this is not deployment approval.

The review covered the integrated source, not only builder summaries: contact extraction and attribution, depth selection and refresh/retry identity, workbook reconciliation and power semantics, correction and suppression replay, public read exposure, internal membership retraction, migration 0045, and benchmark claims. The reviewer made no application-code changes, database writes, migrations, provider calls or deployment actions.

## Follow-up at `993b6c7`

The lead identified an additional P1 after the earlier review: a surviving phone method's shared quote could expose a suppressed email. `993b6c7` now scrubs nested public/reported methods as well as evidence, reason and correction history. The reviewer independently reproduced closure without a database: the email disappears from those fields, the phone value/href remain unchanged, and the surviving method quote equals its redacted evidence quote.

**P1 found at `993b6c7` — source-extracted title bypasses method suppression (corrected in the final readback below).** The same overlay does not scrub the candidate's top-level `title`. The reviewer used the actual HTML parser and people extractor with the heading `Avery Example, Procurement Manager hidden@example.test`; it produces the literal title `Procurement Manager hidden@example.test`. A separate no-database execution of `_apply_contact_privacy` with an active global email suppression removes the method and redacts the evidence, but returns that title unchanged. Normal cards and search can therefore expose the suppressed method. Apply the privacy policy to contact-bearing display strings as well as nested evidence/method fields, and cover this real extraction-to-projection path. This finding was sent immediately to the coordinator and lead.

The earlier **91 passing focused tests remain evidence for `7954e29` only**; they were not rerun at `993b6c7`. New independent execution at `993b6c7` consists of the read-only parser/privacy reproductions described above. No database writes, provider calls or application-code edits were made.

## Final integrated readback at `9316c36`

The reviewer inspected the full application delta from `993b6c7` through `9316c36`, including the exact integrated privacy code and tests, which match reviewed builder commit `1f67936`. The title finding is closed by collecting contact-like values from candidate display strings and recursively redacting the entire contact projection. One shared protected-metadata set preserves typed identity, hash, version, time and enum fields. Free-text `extraction_location` is deliberately not protected. Both selective redaction and subject/overflow suppression cover nested display fields. The real HTML parser→people extractor title regression exercises this boundary; stored claims and sources remain unchanged.

Two additional pre-freeze privacy findings were corrected: mixed international/NANP lines now use both match sets, and global-person suppression follows retained person keys for the exact same `(project_id, entity_key)` when a refreshed claim/source has a different or missing person link. This is a privacy lookup, not identity creation or merging. Distinct historical person keys are bounded to 128 per exact subject, with overflow failing closed only for that subject. The initially proposed global-cohort cap was rejected during review; the final windowed query and regression preserve 129 unrelated one-link subjects beside an overflowing subject.

Independent no-database reproductions on the matching reviewed privacy implementation confirmed title/nested-field/shared-quote redaction while retaining UUIDs and the surviving phone value/href, plus historical-person suppression and isolation of an overflowing subject. The reviewer inspected the builder's database regressions for source-change/new-claim suppression, explicit reinstatement, free-text provenance, mixed phone formats and per-subject bounds; their execution results remain builder/coordinator evidence.

`ffb5a9c` additionally recognizes canonical owner-energy and owner-construction contact roles. It still requires a usable named method, excludes EPC from that owner-role test, and leaves purchasing authority unconfirmed. `df79427` classifies the observed standalone `Rows` footer as metadata only when every other source cell is empty; populated projects named Rows remain records. The raw source row is retained. No other application behavior changed in this final delta.

The coordinator reports isolated actual-workbook staging of four batches and 4,520 inactive source rows with replay/provenance checks and zero canonical project/company/need creation. The reviewer did not execute that staging, and it is not evidence of production matching or commercial qualification.

## Findings and closure

| Finding raised during review | Integrated correction and independent readback |
|---|---|
| Corrupt suppression chains returned a state readers did not recognize, failing open | Ledger readers now fail closed on broken versions and invalid transitions. Conflicted chains cannot be reinstated through the ordinary writer. Expected-version and idempotency checks retain attributed history. |
| Raw values, hrefs and formatted phone numbers produced different privacy keys | Canonical email/href and phone keys now agree, including domestic NANP versus `+1` forms. Company-scoped method keys no longer depend on a transient person label. |
| Global privacy rules were skipped without company identity, and public history bypassed suppression | Shared buying-chain projection applies global method/person rules independently of company resolution and applies the overlay to public historical reads. Ordinary search and contact cards filter suppressed subjects. |
| Per-contact ledger/person queries created an N+1 read path | The shared buying-chain cohort reads identity links and relevant ledger states in batches. Raw evidence and ledger rows are retained. |
| Removing active methods left suppressed values in evidence/correction history | Privacy lookup now also considers retained contact-like values. Public evidence and correction payloads are scrubbed; more than 64 retained values suppresses the contact-bearing candidate rather than skipping the policy. |
| Cross-line phone matching combined separate numbers and skipped privacy lookup | `7954e29` extracts phone keys per evidence line, with explicit NANP matching. Independent no-database reproductions pass for separate quote records, a multiline quote, and adjacent same-line NANP numbers. Each queries the ledger and removes the suppressed number. |
| Correction writers accepted unsupported positive semantics, malformed values, or wrong-project idempotent replay | Scope validation precedes replay. Values are typed and allowlisted, cited support must be current and field-appropriate, and positive assertions must reuse an existing extracted assertion/method. Explicit contact-kind handling and null clearing now use the matching contact citation. Corrections do not create independent verification. |
| Explicit person-card emails could become generic company methods outside a small URL allowlist | Parser-bound person methods are excluded from generic promotion independently of named-role admission. Supported cards work on arbitrary paths; previously misattributed generic methods are removed from the new projection. The original source remains retained. |
| Adaptive research compared display roles with raw enums and depended on changing clock-based priority | Role normalization is shared. A stable standard/deep profile is included in the research digest and queued payload. Retrieval remains capped at four or six URLs within the existing deadline; repeated yield is deduplicated. Existing paid-provider gates and failed-refresh generation semantics remain. |
| Workbook reconciliation loaded the entire Project catalog and emitted unbounded candidate details | Exact-name and probable state/company candidate pools now have explicit bounds, comparison caching and per-row output caps. Truncated pools cannot produce an adopted or unique probable identity. Echoed header rows are retained as metadata rather than records. |

One nonblocking capacity limitation remains: reconciliation's identity and membership evidence lookups scale with the current memberships of referenced companies/projects. The new project-pool and output caps should not be described as a constant bound on all database work. No canonical promotion or correctness shortcut is taken when the new matching limits are reached.

## Evidence, authorization and preservation

Contact cards retain literal source attribution and bounded DOM associations. A role, published method or source-check date does not establish mailbox deliverability, purchasing authority or project assignment. Unsupported methods are not guessed. Power presentation distinguishes source-reported and evidence-supported claims; facility/IT capacity is not silently converted to temporary demand. Workbook values remain unverified assertions, residual gap remains unknown, and reconciliation cannot promote a project to a commercial tier.

The new membership service is an internal negative correction only. It checks the exact project/company/membership, source evidence/hash and expected version before idempotent replay, serializes with the existing source writer, and appends its audit event while preserving physical project identity and original evidence. The CLI defaults to a read-only preview and requires explicit execution plus the expected database name. No public editing route was added; public mutations remain limited to authentication.

Migration 0045 is additive and does not rewrite existing evidence. Downgrade refuses to drop a populated privacy ledger. The documented rollback requires a privacy-compatible application or disabled contact surfaces and refresh workers; an older image that ignores the ledger is not a safe rollback. The reviewer inspected this behavior but did not execute database migrations.

TX/OK/NM physical eligibility, the 300 kW floor, distinct physical projects, unknown-versus-zero handling and existing qualification arithmetic remain in force. Exceptional controls are not prerequisites for autonomous discovery, research or qualification.

## Independent verification

On exact source `7954e29`, the reviewer ran the following focused tests without database fixtures: **91 passed**, with one Starlette/httpx deprecation warning.

```text
uv run pytest tests/unit/test_company_contact_tools.py \
  tests/unit/test_enrichment_planner.py tests/unit/test_workbook_import.py \
  tests/unit/test_opportunity_intelligence_contract.py \
  tests/unit/test_autonomous_api_surface.py -q
```

The reviewer also ran read-only parser/privacy reproductions and `git diff --check`. Database-backed correction, membership concurrency, schema preservation, complete backend and browser execution are coordinator validation; their final exact-source results must be attached before regression acceptance.

## Commercial and deployment limits

The four actual workbooks have been supplied, but their source rows are not a substitute for 25 actual current published GridLens opportunities. The benchmark selects distinct projects from the current published generation and explicitly labels commercial actionability, independent identity accuracy and independent mailbox verification as untested/unknown. The reported six-project local Austin corpus is not a completed 25-opportunity benchmark.

**Commercial P0 and production deployment remain open/on hold.** This source review does not establish actual production contact yield, the requested 25-opportunity benchmark, current territory coverage, daily autonomous-cycle performance, paid-provider readiness or deployed behavior. No merge, deployment, paid-provider activation or production-data write is authorized by this receipt.
