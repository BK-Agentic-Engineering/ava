#!/usr/bin/env sh
set -eu
cd /code
exec python -m lifemate.deploy "$@"
