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
    docker run --rm postgres:18.6 pg_dump --format=custom --no-owner "${BACKUP_DATABASE_URL}" \
      | docker run --rm -i \
          -e AWS_ACCESS_KEY_ID="${SPACES_KEY}" -e AWS_SECRET_ACCESS_KEY="${SPACES_SECRET}" \
          amazon/aws-cli:2.27.50 s3 cp - "s3://${SPACES_BUCKET}/backups/gridlens-${stamp}.dump" \
          --endpoint-url "https://${SPACES_REGION}.digitaloceanspaces.com"
    echo "backup gridlens-${stamp}.dump uploaded" ;;
  *) echo "usage: $0 collect|alert|backup" >&2; exit 2 ;;
esac
