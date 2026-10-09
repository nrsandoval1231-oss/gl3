# Initial A6 controller validation — not accepted

Candidate: `0b81c2de358213d7d5760aebc8faa3f659924c34`.

The full backend run returned 1423 passed, 3 failed, 2 skipped, 7 warnings and 8 errors. Raw output is retained in `.artifacts/root-a6-final-full.log`. Eight errors arose from the new call-fact fixture requiring the builder's exact database name; a bounded test-only repair was dispatched. Three authentication failures arose because the controller assigned the application database and destructive disposable migration-test database to the same database. The controller prepared a separate, newly created application test database at schema 0017 for the next run.

The first browser run returned 61 passed and 1 failed: its newly created database had not been migrated, so authentication tables were absent. Original text output and native trace are retained in `.artifacts/root-a6-final-browser.log` and `.artifacts/root-a6-final-browser-results`. After applying schema 0017, the same source candidate passed all 62 browser checks in 44.4 seconds. The new output is `.artifacts/root-a6-final-browser-migrated-browser.log` with a separate native output directory. Neither failed output was overwritten.

Static checks, exact generated OpenAPI (34 paths), retained semantic comparison (1167 records, 1149 groups, 17 searches), all 24 public pages, and retained payload parity passed on the original product source. The upcoming repaired candidate differs in the test database guard only and requires a new full backend gate and source binding. No independent acceptance or parent completion is claimed.

An initial chained migration invocation lost its relative wrapper path because the wrapper changes working directory; the repeated upgrade and drift check subsequently passed using an absolute wrapper path. Some diagnostic tool output bytes were not retained as files and remain UNKNOWN. Available native browser diagnostics are preserved using extended Windows paths.
