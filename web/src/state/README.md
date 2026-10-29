# Session privacy cleanup

`clearContinuity()` removes GridLens-prefixed legacy session-storage entries and notifies mounted views when authentication ends. Storage access may be denied; cleanup handles that safely. Current application code does not create or restore tab-local navigation or call-entry drafts.
