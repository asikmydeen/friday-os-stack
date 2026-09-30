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

echo "bootstrap.sh writes .env and stops. It does not start Friday." >&2
echo "The core images build from this tree. See scripts/smoke-core.sh." >&2
echo "Empty tokens make friday, board, memory-mcp, and executor exit." >&2
exit 1
