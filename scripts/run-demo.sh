#!/bin/sh
# Run from a source checkout; local configuration stays in child processes.
set -eu
HOMEBOUND_SOURCE_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$HOMEBOUND_SOURCE_ROOT"
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
HOMEBOUND_PYTHON="${HOMEBOUND_PYTHON:-$HOMEBOUND_SOURCE_ROOT/.venv/bin/python}"
if [ ! -x "$HOMEBOUND_PYTHON" ]; then
  echo "Create the Python environment with make install first." >&2
  exit 2
fi
if [ "${1:-}" = "--with-services" ]; then
  node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 14)) { console.error("Select Node.js 22.14+ first; .node-version pins the tested version."); process.exit(2); }'
fi
exec "$HOMEBOUND_PYTHON" -m app.cli.web "$@"
