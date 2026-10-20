"""Read-only GL3 release baseline: emit selected metadata, never environment values."""
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

names = ["gridlens-" + name + "-1" for name in ("api", "worker", "browse", "web", "db")]
inspected = json.loads(subprocess.check_output(["docker", "inspect", *names], text=True))
containers = [{"name": item["Name"], "id": item["Id"], "image_id": item["Image"],
               "image_tag": item["Config"]["Image"], "running": item["State"]["Running"],
               "started_at": item["State"]["StartedAt"]} for item in inspected]
ready = subprocess.check_output(["docker", "exec", "gridlens-web-1", "wget", "-qO-",
                                 "http://api:8000/health/ready"], text=True)
query = "SELECT json_build_object('schema',(SELECT version_num FROM alembic_version),'fresh_worker',EXISTS(SELECT 1 FROM worker_heartbeats WHERE last_seen_at>now()-interval '60 seconds'),'logical_calls',(SELECT count(*) FROM logical_calls),'unknown_calls',(SELECT count(*) FROM logical_calls WHERE status='SENT_OUTCOME_UNKNOWN'),'title_tables',(SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename IN ('power_need_titles','power_need_title_versions')));"
database = json.loads(subprocess.check_output([
    "docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000",
    "gridlens-db-1", "psql", "-U", "gridlens", "-d", "gridlens_restore_20261014",
    "-X", "-At", "-c", query], text=True))
hashes = {name: hashlib.sha256((Path("/etc/gridlens") / name).read_bytes()).hexdigest()
          for name in ("compose.app.yaml", "runtime.env", "start-gridlens.py")}
print(json.dumps({"checked_at": datetime.now(UTC).isoformat(), "read_only": True,
                  "containers": containers, "readiness": json.loads(ready),
                  "database": database, "configuration_sha256": hashes}))
