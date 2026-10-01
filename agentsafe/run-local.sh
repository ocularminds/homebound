#!/bin/sh
set -eu

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/agentsafe/.env"
if [ ! -f "$CONFIG_FILE" ]; then
  echo "Create agentsafe/.env from agentsafe/.env.example first." >&2
  exit 2
fi

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
NODE_MINOR="$(node -p 'Number(process.versions.node.split(".")[1])')"
if [ "$NODE_MAJOR" -lt 22 ] || { [ "$NODE_MAJOR" -eq 22 ] && [ "$NODE_MINOR" -lt 14 ]; }; then
  echo "AgentSafe requires Node.js 22.14 or newer; select a supported runtime first." >&2
  exit 2
fi

set -a
. "$CONFIG_FILE"
set +a
export EXECUTOR_JOURNAL_DIR="${EXECUTOR_JOURNAL_DIR:-$PROJECT_ROOT/audit/agentsafe}"
mkdir -p "$EXECUTOR_JOURNAL_DIR"
exec node "$PROJECT_ROOT/agentsafe/server.mjs"
