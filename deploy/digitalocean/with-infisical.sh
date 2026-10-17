#!/usr/bin/env bash
# Use an existing authenticated Infisical CLI identity. Never export secrets to a file.
# Secrets live in Infisical (project 06ded1a4-5c85-426a-a833-d40358529795,
# environment slug `dev`, path `/`). Expected secret names: TYPESAFE_API_KEY and
# OPENAI_API_KEY. Compose forwards both to the api/worker/migrate containers only.
# Example: INFISICAL_PROJECT_ID=06ded1a4-5c85-426a-a833-d40358529795 \
#          INFISICAL_ENVIRONMENT=dev INFISICAL_SECRET_PATH=/ ./with-infisical.sh ...
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
