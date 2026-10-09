# A3 attempt history

Final successful evidence is in the adjacent command logs. Earlier failed draft
checks appeared in the active task transcript and were corrected as follows:

1. Focused test collection first failed because `api/app.py` still imported the
   removed `token_for` symbol. The stale import was removed; a persisted-session
   compatibility helper was later added for existing integration tests.
2. The first concurrency assertion admitted 5 rather than the test's expected 3
   attempts. The limiter had copied Pydantic settings into module constants at
   import time, so the changed test limit was ignored. The implementation now
   reads configured limits inside each serialized transaction.
3. The expired-window recovery draft failed because a test session context
   rolled back changes on close. The test now uses a committing transaction.
4. The isolated auth fixture first tried to patch `SessionLocal` on the FastAPI
   object instead of the API module. It now patches the module's factory; the
   representative existing integration test confirms that its injected test
   factory is used by the persisted-session helper.

These were one bounded product correction (runtime settings lookup) and test
harness corrections. No unchanged failing approach was retried. Final focused
auth/API/security checks pass: 13 tests. The representative existing API
integration check passes: 1 test.
