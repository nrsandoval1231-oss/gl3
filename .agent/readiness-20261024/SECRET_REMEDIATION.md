# Taylor public fixture secret remediation

## Finding

GitHub secret scanning alert 1 identifies a Google Maps key in original Taylor HTML fixture content from source commit `fa5e667045ddeb448c16ed0351d91ea35ad83ed7`. The alert points to the `GoogleMapsKey` hidden fields in the two Taylor source pages. Credential validity is `UNKNOWN`.

## Current fixture state

At assigned base `37e0691120904f6e11faa208327d46e4e46856af`, both named fixtures are already curated HTML extracts. Neither contains a Google API key format or the original hidden key field. This repair adds a regression test that rejects Google API key-shaped strings in both public fixtures. Current fixture cleanup was inherited before this audit; this change does not claim to have fixed a current fixture leak. No fixture, permit, source, or parser content was changed.

## Validation and limits

The regression test and existing Taylor parser/planning tests are run as recorded in the completion handoff. This confirms only the current checkout's fixture sanitation. The original source remains in public Git history, and alert 1 remains open. The publisher/provider account owner must determine whether the key is restricted or actively used and revoke or rotate it if needed. No credential validity check, provider call, alert dismissal, history rewrite, or claim of alert resolution was performed here.

## Candidate verification

- `uv run --project backend --extra dev --offline --python 3.11 pytest backend/tests/unit/test_taylor_newsflash.py backend/tests/unit/test_taylor_planning.py` — 22 passed, exit 0. Provider key environment variables were unset; required application settings used test-only placeholders. No `.env` file was present.
- `ruff check backend/tests/unit/test_taylor_newsflash.py` — exit 0.
- `ruff format --check backend/tests/unit/test_taylor_newsflash.py` — exit 0.
- `git diff --check 37e0691120904f6e11faa208327d46e4e46856af` — exit 0.
