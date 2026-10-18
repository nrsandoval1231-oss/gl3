# Intelligence integration: checkpoint learning

STATE: main 49121eb, isolated worktree; B1 tests passed at 5daeb72.
DECISION: independent financial/authority review before provider integration.
ACTION: Sol reviewed exact B1 and returned FIX; raw review retained unchanged.
OUTCOME: five blocking findings repaired in 9aa3117; controller 39 focused tests
pass. Acceptance still waits final integrated review.

DETERMINISTIC EVALUATION: fresh retained-copy upgrade 0018 through 0027 succeeds;
original core fields/digests preserved. Schema check finds two monitoring metadata
mismatches despite passing create_all fixtures. C2 repairs are READY. Local full
dump/restore preserves evidence/jobs/reservations and blocks dispatched-call replay.

ATTRIBUTION: create_all fixtures exercise ORM schema, not migration parity. A
concurrent destructive fixture collision also made one legacy run inconclusive;
each builder now owns an exclusive database as well as disjoint files.

CANDIDATE LESSON: prove fresh/repeat upgrade and schema parity separately from ORM
fixtures; assign mutable database ownership. Metrics: schema drift operations
target zero; cross-lane destructive-database overlap target zero. Validation and
promotion wait final gates/independent review. No canonical requirement or global
memory changed. Failed checks remain evidence, not success.

NEXT DIRECTION: CONTINUE E/F, C2/D2/task contexts/operational tooling, then freeze,
deterministic gates and Sol review. Missing provider/cloud/time proof stays OPEN.
