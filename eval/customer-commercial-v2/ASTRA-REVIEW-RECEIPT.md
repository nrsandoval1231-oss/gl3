# Reference context v2 independent review

Status: accepted for the additive reference-context artifact only. This is not
acceptance of a parser, runtime, scorer, or commercial metric result.

## Reviewed artifacts

- Contract: `REFERENCE-INPUT-CONTRACT-v2.md`
  (SHA-256 `5c7a469067364320461d95ed7cc6b331a0ea45fcda0920ee596eac258004de1e`)
- Annotation overlay: `source-context-annotations.json`
  (SHA-256 `157853e01970a66ccc92be8e52856c87dcb7c18089ca11e28e0ac7e2d2c41370`)
- Builder: `build_reference_context.py`
  (SHA-256 `9aeb8927c0884f1ce5086753cb9c9986b80b2c9adb461421e218962dacd22c7a`)
- Integrity tests: `test_reference_context_v2.py`
  (SHA-256 `c1f9c82cffca8cf692dd7c17f40e9072f0e427e32a5b887483c1623417f144f7`)
- V1 preservation manifest: `v1-preservation-manifest.json`
  (SHA-256 `21d07df3d73a0e3963e6595f5c59c307267d23c62e85747371e944e4aeb31f26`)

The review covered all 20 organization annotations and their source bundles.
All 64 assertion evidence references resolve to exact source spans. The
context partition is 64 = 59 subject-bound + 3 excluded + 2 unresolved. The
separate historical scoring partition is 32 physical-capacity assertions
included + 2 physical-capacity assertions excluded + 30 timeline assertions
included. Aligned's Ohio state/host-park context is supported while the
county-level display remains unverified by the assigned site wording.

## Verification

The independent reviewer ran the builder check and all seven v2 integrity
tests against the current hashes. The builder reproduced the exact overlay
hash above; all seven tests passed. The tests verify all 20 records, all 64
assertions, exact quote offsets/hashes, source-reference resolution, the V1
metric denominator, and byte preservation of all 114 files present in the V1
tree when this overlay was created.

The builder and test files were formatted with Ruff after the first review.
No pre-format source copies were retained, so the reviewer did not compare
pre/post ASTs and does not certify AST identity. The reviewer reread the
current builder and test semantics, reran the builder check and tests, and
found no behavioral difference or review blocker.

This review does not modify or validate the existing V1 scorer, production
parser, runtime identity, source admission, or native end-to-end publication.
V2 remains an additive annotation proposal; no V2 score is reported here.
