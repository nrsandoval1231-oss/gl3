# Identity continuity controlled comparison

**The 640 MW and 720 MW values and withdrawal titles are synthetic revision controls over real retained DataBank text. They are not observed publisher developments or statements about DataBank’s actual announced capacity. The unchanged 20-company corpus remains the source for factual evaluation.**

The first integration draft compared an identity from an uncommitted enrichment transaction. That was an invalid comparison, and the new fixture was corrected to commit the initial state. This receipt uses the corrected fixture.

The coordinator then restored only the original 55-line identity-carry block from `73e01a73` into the current enrichment function **in memory**. Native ingestion, source bindings, current company-role producers and the test remained unchanged. No product source file was edited. The exact original block and hash are retained here. This is not a full-main checkout test.

The original carry logic failed the exact UUID-continuity assertion after the same DataBank URL/project changed from480MW to640MW. Diagnostic data confirmed two durable runs, two claims and two source versions. The fixture therefore detects the original continuity deficiency after correcting its transaction error. Candidate results require a separate passing run; this negative control is not a candidate failure or production proof.

From a configured disposable test environment, run from `backend/` (both database names must end in `_test`):

```sh
PYTHONPATH=../docs/validation/customer-intelligence-20261112/identity-continuity \
  .venv/bin/python -m pytest -p original_carry_plugin \
  tests/integration/test_real_customer_commercial_runtime.py::test_retained_company_project_records_enter_native_pipeline -q
```

The expected outcome of this control is failure at UUID continuity. Run the same test without `-p original_carry_plugin` to verify the candidate. The plugin applies only to that process and does not rewrite code, history, or an existing test. It fails closed if the function no longer contains the expected replacement boundaries. Do not run against retained or production databases.
