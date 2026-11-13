#!/usr/bin/env bash
# Host entry point for scheduled jobs. Usage: gridlens-run.sh collect|alert|backup
set -euo pipefail
cd /opt/gridlens
compose=(docker compose -f deploy/digitalocean/compose.prod.yaml --env-file .env.prod)

case "${1:-}" in
  collect)
    "${compose[@]}" run --rm --no-deps worker uv run python -m gridlens.jobs.refresh_sources ;;
  alert)
    "${compose[@]}" run --rm --no-deps worker uv run python -m gridlens.jobs.alerts ;;
  backup)
    set -a; . ./.env.prod; set +a
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    object_ref="s3://${SPACES_BUCKET}/backups/gridlens-${stamp}.dump"
    # Secrets are passed to containers by variable name (`-e NAME`), never as
    # argv values, so they do not appear in `ps` or `docker inspect` command lines.
    # pg_dump reads the connection string from the container environment.
    BACKUP_DATABASE_URL="${BACKUP_DATABASE_URL}" \
      docker run --rm -e BACKUP_DATABASE_URL postgres:18.6 \
        sh -c 'exec pg_dump --format=custom --no-owner "$BACKUP_DATABASE_URL"' \
      | AWS_ACCESS_KEY_ID="${SPACES_KEY}" AWS_SECRET_ACCESS_KEY="${SPACES_SECRET}" \
        docker run --rm -i -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
          amazon/aws-cli:2.27.50 s3 cp - "${object_ref}" \
          --endpoint-url "https://${SPACES_REGION}.digitaloceanspaces.com"
    receipt_tmp="/opt/gridlens/operational-receipt.json.tmp"
    python3 - "${receipt_tmp}" "${object_ref}" "${DEPLOYED_SHA:-UNKNOWN}" <<'PY'
import json, os, sys
from datetime import datetime, timezone
path, reference, deployed_sha = sys.argv[1:]
with open(path, "w", encoding="utf-8") as output:
    json.dump({"version": 1, "recorded_at": datetime.now(timezone.utc).isoformat(),
               "backup_reference": reference, "deployed_sha": deployed_sha}, output)
    output.write("\n")
    output.flush()
    os.fsync(output.fileno())
os.replace(path, "/opt/gridlens/operational-receipt.json")
PY
    echo "backup gridlens-${stamp}.dump uploaded" ;;
  *) echo "usage: $0 collect|alert|backup" >&2; exit 2 ;;
esac
