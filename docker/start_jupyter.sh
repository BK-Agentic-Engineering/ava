#!/usr/bin/env sh
set -eu
cd /code
exec jupyter lab --port 9777 --ip 0.0.0.0 --allow-root --no-browser \
  --IdentityProvider.token=zac2026 "$@"
