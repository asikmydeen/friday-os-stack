#!/usr/bin/env bash
# EXPERIMENTAL — this script is a placeholder. It does not yet produce a
# working instance. See README.md "Build order".
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Wrote .env from .env.example. Edit it before continuing." >&2
  exit 1
fi

echo "bootstrap.sh is not implemented yet beyond writing .env." >&2
echo "Next: ./scripts/bootstrap-memory.sh, then 'docker compose --profile core --profile chat up'." >&2
exit 1
