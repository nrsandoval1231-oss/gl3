# Worker planning and liveness lanes

The worker runs one durable job at a time in a fixed job-execution lane. A
separate heartbeat lane records process liveness, while source discovery,
pursuit-question planning, and watch-monitor planning use separate fixed lanes
under their existing enable flags. Every planner iteration and heartbeat write
uses its own short database transaction. Planner cadence and retry timing remain
persisted in `PlannerState`; an isolated planner failure is logged and does not
stop other lanes.

Heartbeat means that the worker process is alive. It does not mean an
acquisition completed or that a source is fresh or healthy. On shutdown, the
stop event wakes idle lanes and the worker joins all lanes to one finite deadline.
A currently blocked job is logged if it exceeds that bound; it is not allowed to
hold shutdown indefinitely.

This scheduler change does not impose a total job deadline or a global HTTP
admission cap. Those remain separate controls; a long-running job still occupies
the single job-execution lane until it returns.
