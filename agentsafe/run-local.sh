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
export HOMEBOUND_DOSSIER_ARCHIVE_DIRECTORY="${HOMEBOUND_DOSSIER_ARCHIVE_DIRECTORY:-$PROJECT_ROOT/audit/dossiers}"

node "$PROJECT_ROOT/agentsafe/dossier-archive-server.mjs" &
ARCHIVE_PID=$!
EXECUTOR_PID=""
cleanup() {
  if [ -n "$EXECUTOR_PID" ]; then kill "$EXECUTOR_PID" 2>/dev/null || true; fi
  kill "$ARCHIVE_PID" 2>/dev/null || true
  if [ -n "$EXECUTOR_PID" ]; then wait "$EXECUTOR_PID" 2>/dev/null || true; fi
  wait "$ARCHIVE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

node "$PROJECT_ROOT/agentsafe/server.mjs" &
EXECUTOR_PID=$!
set +e
wait "$EXECUTOR_PID"
STATUS=$?
set -e
exit "$STATUS"
