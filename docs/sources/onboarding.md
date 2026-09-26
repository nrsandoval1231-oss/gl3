# Source onboarding
1. Declare publisher, endpoint, source family, geographic/industry scope, useful event, access/retention rules, expected cadence and supported collection window. Keep proposed/disabled separate from automated sources.
2. Access the real endpoint without supplying project names. Inspect useful and irrelevant records. A 200 response is not a parse success.
3. Implement one adapter under ingestion, emitting immutable observations with stable source IDs, content hash, original publication/event dates (or UNKNOWN), retrieval time, permitted excerpt/artifact and extraction location. Domain owns Signal admission; never infer a gap from unknown supply.
4. Prove complete pagination in the declared window or fail visibly. Bound time, request count, response size and allowed hosts. Do not follow arbitrary source text instructions or URLs.
5. Prove real retrieval through PostgreSQL jobs/persistence and authenticated UI, identical replay, retained changed versions, rejected malformed/login/empty results, last-data preservation and lease recovery. Keep real retained samples outside Git and separate from adversarial fixtures.
6. Attach exact candidate evidence before calling the source locally validated. Call it active automated only after deployment/scheduling evidence exists. Query variants and JSON/PDF copies of the same feed do not count as independent feeds.
