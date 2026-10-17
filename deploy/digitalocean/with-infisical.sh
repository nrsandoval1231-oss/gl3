#!/usr/bin/env bash
# Use an existing authenticated Infisical CLI identity. Never export secrets to a file.
set -euo pipefail
: "${INFISICAL_PROJECT_ID:?set the existing GL3 Infisical project ID}"
: "${INFISICAL_ENVIRONMENT:?set the existing environment slug}"
: "${INFISICAL_SECRET_PATH:?set the existing secret folder path}"
if ! command -v infisical >/dev/null 2>&1; then
  echo 'Infisical CLI unavailable; existing runtime access must be connected.' >&2
  exit 1
fi
if [ "$#" -eq 0 ]; then
  echo 'usage: with-infisical.sh command [args...]' >&2
  exit 2
fi
exec infisical run --projectId="$INFISICAL_PROJECT_ID" \
  --env="$INFISICAL_ENVIRONMENT" --path="$INFISICAL_SECRET_PATH" -- "$@"
