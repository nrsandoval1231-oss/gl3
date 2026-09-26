#!/bin/sh
set -eu
createdb --username "$POSTGRES_USER" gridlens_test
