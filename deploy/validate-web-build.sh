#!/bin/sh
# Only production web-image builds require a source revision. Backend-only
# Compose operations must remain usable without frontend build metadata.
set -eu

if [ "${VITE_DEPLOYMENT_ENVIRONMENT:-}" != "production" ]; then
    exit 0
fi

build_sha=${VITE_GIT_SHA:-}
case "$build_sha" in
    ''|*[!0-9a-fA-F]*)
        echo 'Production web builds require an actual 40-character commit SHA in GRIDLENS_BUILD_SHA.' >&2
        exit 1
        ;;
esac
if [ "${#build_sha}" -ne 40 ]; then
    echo 'Production web builds require an actual 40-character commit SHA in GRIDLENS_BUILD_SHA.' >&2
    exit 1
fi
