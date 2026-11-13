# Publication date boundary review — November 13, 2026

## Accepted bounded rule

The retained-company-project adapter sets publication day only from exact date
metadata or a recognizable publication header: a standalone date/published
line, or a city plus recognized U.S. state dateline separated from the date by
a dash. A date in article prose is not a publication date. Year, month, and
quarter precision are not promoted to an exact day. The raw metadata is kept
in the version hash and reconstructed by the admission, organization, and
identity-history readers before they accept a source record.

## Exact reviewed implementation hashes

- Adapter `retained_company_projects.py`: `5b8341c8a51d57f651c45fe126df932ad52da0017e79148dece96dcd352a397a`
- New date-boundary tests `test_retained_publication_date_boundary.py`: `5be9d8e4635e6f53f6c79784665cc6ad7636116de2f89d205b9da4fa4e883562`
- Admission reconstruction `signal_admission.py`: `48d4309aceb90993ad5879be50e28072532d919245fd08bdb5be665f0eee2838`
- Organization reconstruction `retained_project_organizations.py`: `5f738b8a7790b0b49467baf2f7830e18033ae92442afae9c82b922c8a3170b0c`
- Identity history reconstruction `identity_reconciliation.py`: `b247bd51cea8a58fd9c98c2d130c51bbb2ca5052d0250a31d5a99ea94e9bff3e`

## Review and validation

Astra independently checked the exact adapter and test hashes above. Six
pure-date controls covered the prose/capitalization negatives and the
Indianapolis, Indiana dateline; six source reparse controls covered real
DataBank and CyrusOne records, explicit same-day metadata, and a forged
publication-day mutation. DataBank remains dated September 10, 2024, and
CyrusOne remains dated July 30, 2025. Astra accepted the bounded change with no
remaining P1/P2 in this area.

Local validation on this revision passed 47 focused date/admission/organization
tests, mypy, and Ruff. The native runtime integration
`test_retained_company_project_records_enter_native_pipeline` passed on a
fresh disposable database. The run also verifies the current native record
and saved API state after the metadata became part of the version hash.

## Receipts and limits

- Native runtime: [`native-runtime-replay-publication-final-20261113.json`](native-runtime-replay-publication-final-20261113.json). Its fresh database was `gl3_customer_runtime_20261113085209_c4098418_test` and was dropped after the run.
- Source-text oracle replay: [`source-text-scope-replay-publication-final-20261113.json`](source-text-scope-replay-publication-final-20261113.json).

The native runtime surfaces CyrusOne's source-reported operational deadline:
expected operation by Q4 2026, with quarter precision, in the July 30, 2025
source. This is not a construction-start or energization date. The separate
oracle-scoped text replay still scores that timeline assertion as a false
negative; the runtime output is not counted as a scoring true positive.

This review establishes behavior for the bounded header/date controls and the
retained DataBank/CyrusOne native records. It is not a measure of publication
date accuracy across arbitrary publishers or production feeds.
